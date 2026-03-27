import asyncio

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from hughie.config import get_settings
from hughie.core.state import HughieState
from hughie.llm.codex_chat_model import CodexChatModel
from hughie.memory import brain_store, conversation_store, link_store
from hughie.memory.consolidator import maybe_consolidate
from hughie.tools.brain_tools import BRAIN_TOOLS

_llm: CodexChatModel | None = None


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
    """Load brain notes and conversation history from DB."""
    session_id = state["session_id"]

    # Last user message for semantic search
    user_text = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            user_text = str(msg.content)
            break

    # Brain notes semantic search
    notes = await brain_store.search_notes(user_text, limit=5) if user_text else []
    brain_context = ""
    if notes:
        lines = [f"- [{n.type}] {n.title}: {n.content}" for n in notes]

        links = await link_store.get_links_for_notes([n.id for n in notes], limit=12)
        connected_note_lines: list[str] = []
        path_lines: list[str] = []
        seen_note_ids = {n.id for n in notes}
        seen_path_targets: set[str] = set()

        for link in links:
            source_title = link.source_note_title or "nota relacionada"
            if link.target_kind == "note" and link.target_note_id and link.target_note_id not in seen_note_ids:
                seen_note_ids.add(link.target_note_id)
                if link.target_note_title and link.target_note_content:
                    connected_note_lines.append(
                        f"- ({link.relation_type} de {source_title}) "
                        f"[{link.target_note_type or 'fact'}] {link.target_note_title}: {link.target_note_content}"
                    )
            elif link.target_kind in {"file", "directory"} and link.target_path and link.target_path not in seen_path_targets:
                seen_path_targets.add(link.target_path)
                path_lines.append(
                    f"- ({link.relation_type} de {source_title}) [{link.target_kind}] {link.target_path}"
                )

        sections = ["O que você sabe sobre o usuário e o projeto:\n" + "\n".join(lines)]
        if connected_note_lines:
            sections.append("Notas conectadas:\n" + "\n".join(connected_note_lines))
        if path_lines:
            sections.append("Arquivos e diretórios relacionados:\n" + "\n".join(path_lines))
        brain_context = "\n\n".join(sections)

    # Load conversation history from DB as ordered list
    turns = await conversation_store.get_recent(session_id, limit=20)
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

    system_content = settings.system_prompt
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
    return {"messages": [response]}


async def save_memory(state: HughieState) -> dict:
    """Persist user message and assistant response to DB."""
    session_id = state["session_id"]
    messages = state["messages"]

    last_user = None
    last_assistant = None
    for msg in reversed(messages):
        if last_assistant is None and isinstance(msg, AIMessage) and not msg.tool_calls:
            last_assistant = msg
        elif last_user is None and isinstance(msg, HumanMessage):
            last_user = msg
        if last_user and last_assistant:
            break

    if last_user:
        await conversation_store.save_turn(session_id, "user", str(last_user.content))
    if last_assistant:
        await conversation_store.save_turn(session_id, "assistant", str(last_assistant.content))

    # Fire consolidation in background — does not block the response
    asyncio.create_task(maybe_consolidate(session_id))

    return {}
