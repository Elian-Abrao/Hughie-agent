import asyncio
from collections.abc import Awaitable, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from hughie.config import get_settings
from hughie.core.state import HughieState
from hughie.llm.codex_chat_model import CodexChatModel
from hughie.memory import conversation_store
from hughie.memory.consolidator import maybe_consolidate
from hughie.memory.rag import retrieve_context_v2
from hughie.prompts import load as load_prompt
from hughie.tools.brain_tools import BRAIN_TOOLS

_llm: CodexChatModel | None = None
ProgressCallback = Callable[[str, str], Awaitable[None]]


async def _emit_progress(state: HughieState, stage: str, message: str) -> None:
    callback = state.get("progress_callback")
    if callback is None:
        return
    try:
        await callback(stage, message)
    except Exception:
        # Progresso não deve quebrar o fluxo principal do agente.
        return


def init_llm(tools: list) -> None:
    """Initialize the LLM with the full tool list. Call once at startup."""
    global _llm
    _llm = CodexChatModel().bind_tools(tools)


def _get_llm() -> CodexChatModel:
    if _llm is None:
        # Fallback: brain tools only (before registry is loaded)
        return CodexChatModel().bind_tools(BRAIN_TOOLS)
    return _llm


async def retrieve_context(state: HughieState) -> dict:
    """Load ranked RAG context and conversation history from DB — in parallel."""
    session_id = state["session_id"]
    await _emit_progress(state, "context:start", "Buscando histórico recente e memória relevante.")

    user_text = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            user_text = str(msg.content)
            break

    task_context = "\n".join(str(msg.content) for msg in state["messages"] if getattr(msg, "content", ""))

    async def _rag() -> dict:
        if not user_text:
            return {"context": ""}
        return await retrieve_context_v2(query=user_text, task_context=task_context, top_k=10)

    # RAG search and history fetch are independent — run concurrently
    rag_payload, turns = await asyncio.gather(
        _rag(),
        conversation_store.get_recent(session_id, limit=20),
    )
    await _emit_progress(
        state,
        "context:loaded",
        (
            f"Contexto carregado: {len(turns)} mensagem(ns) recentes, "
            f"{len(rag_payload.get('results', []))} nota(s) e {len(rag_payload.get('episodes', []))} episódio(s)."
        ),
    )

    brain_context = rag_payload["context"]
    history = []
    for turn in turns:
        if turn.role == "user":
            history.append(HumanMessage(content=turn.content))
        elif turn.role == "assistant":
            history.append(AIMessage(content=turn.content))

    return {
        "brain_context": brain_context,
        "history": history,
    }


async def chat(state: HughieState) -> dict:
    """Call the LLM with full ordered context."""
    settings = get_settings()
    llm = _get_llm()
    await _emit_progress(state, "model:start", "Consultando o modelo com o contexto consolidado.")

    system_content = settings.system_prompt or load_prompt("system")
    if state.get("brain_context"):
        system_content += f"\n\n{state['brain_context']}"

    # Build complete ordered message list:
    # [system] + [history from DB] + [current turn messages]
    full_messages = (
        [SystemMessage(content=system_content)]
        + state.get("history", [])
        + list(state["messages"])
    )

    response = await llm.ainvoke(full_messages)
    await _emit_progress(state, "model:done", "Resposta inicial do modelo recebida.")
    return {"messages": [response]}


async def save_memory(state: HughieState) -> dict:
    """Persist user message and assistant response to DB."""
    await _emit_progress(state, "memory:save", "Salvando a conversa e agendando atualização de memória.")
    session_id = state["session_id"]
    messages = state["messages"]

    last_user = None
    last_assistant = None
    tool_messages: list[ToolMessage] = []
    tool_call_names: list[str] = []
    for msg in reversed(messages):
        if last_assistant is None and isinstance(msg, AIMessage) and not msg.tool_calls:
            last_assistant = msg
        elif isinstance(msg, AIMessage) and msg.tool_calls:
            tool_call_names.extend(
                str(tool_call.get("name") or "").strip()
                for tool_call in msg.tool_calls
                if str(tool_call.get("name") or "").strip()
            )
        elif isinstance(msg, ToolMessage):
            tool_messages.append(msg)
        elif last_user is None and isinstance(msg, HumanMessage):
            last_user = msg
        if last_user and last_assistant:
            break

    if last_user and not state.get("user_message_presaved"):
        await conversation_store.save_turn(session_id, "user", str(last_user.content))
    if last_assistant:
        await conversation_store.save_turn(
            session_id,
            "assistant",
            str(last_assistant.content),
            metadata={
                "had_tool_calls": bool(tool_call_names or tool_messages),
                "tool_call_names": list(dict.fromkeys(tool_call_names)),
                "tool_message_count": len(tool_messages),
            },
        )

    # Fire consolidation in background — does not block the response
    asyncio.create_task(maybe_consolidate(session_id))
    await _emit_progress(state, "memory:queued", "Conversa salva. Consolidação de memória ficou em background.")

    return {}
