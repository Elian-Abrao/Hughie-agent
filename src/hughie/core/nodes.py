import asyncio

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from hughie.config import get_settings
from hughie.core.state import HughieState
from hughie.llm.codex_chat_model import CodexChatModel
from hughie.memory import brain_store, conversation_store
from hughie.memory.consolidator import maybe_consolidate
from hughie.tools.brain_tools import BRAIN_TOOLS

_llm: CodexChatModel | None = None


def _get_llm() -> CodexChatModel:
    global _llm
    if _llm is None:
        _llm = CodexChatModel().bind_tools(BRAIN_TOOLS)
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
        brain_context = "O que você sabe sobre o usuário:\n" + "\n".join(lines)

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
