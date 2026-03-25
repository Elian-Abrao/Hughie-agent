from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from hughie.memory import brain_store
from hughie.memory.consolidator import run_consolidation


@tool
async def save_brain_note(title: str, content: str, note_type: str = "fact") -> str:
    """Save a note about the user to long-term memory.

    Use this when the user shares preferences, personal facts, projects,
    people they mention, or behavioral patterns worth remembering.

    Args:
        title: Short descriptive title for the note (e.g. "Prefers dark mode")
        content: Full content of the note
        note_type: One of: preference, pattern, project, person, fact
    """
    note = await brain_store.save_note(title, content, note_type)
    return f"Note saved: '{note.title}' (id: {note.id})"


@tool
async def search_brain_notes(query: str) -> str:
    """Search long-term memory for notes relevant to a query.

    Use this when you need to recall something about the user.

    Args:
        query: Natural language description of what you're trying to remember
    """
    notes = await brain_store.search_notes(query, limit=5)
    if not notes:
        return "No relevant notes found."
    lines = [f"[{n.type}] {n.title}: {n.content}" for n in notes]
    return "\n".join(lines)


@tool
async def update_brain_note(note_id: str, content: str) -> str:
    """Update the content of an existing brain note.

    Args:
        note_id: UUID of the note to update
        content: New content for the note
    """
    note = await brain_store.update_note(note_id, content)
    if note is None:
        return f"Note {note_id} not found."
    return f"Note updated: '{note.title}'"


@tool
async def consolidate_memory(
    hint: str,
    state: Annotated[dict, InjectedState],
) -> str:
    """Trigger deep memory consolidation focused on something specific.

    Use this when the user shares something complex or important that should
    be properly stored and linked in long-term memory — like a project
    architecture, a set of preferences, or a major decision.

    The worker will read recent conversation history with your hint as focus
    and update the brain accordingly.

    Args:
        hint: Description of what's important (e.g. "user described the full
              architecture of Hughie Agent including LangGraph and memory layers")
    """
    session_id = state.get("session_id", "")
    if not session_id:
        return "Error: could not determine session."

    n = await run_consolidation(session_id, hint=hint)
    if n == 0:
        return "Consolidation complete. No new information found to store."
    return f"Consolidation complete. {n} brain note(s) created or updated."


BRAIN_TOOLS = [save_brain_note, search_brain_notes, update_brain_note, consolidate_memory]
