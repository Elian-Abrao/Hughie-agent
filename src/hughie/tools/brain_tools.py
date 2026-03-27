from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from hughie.memory import brain_store, link_store
from hughie.memory.consolidator import run_consolidation


@tool
async def save_brain_note(title: str, content: str, note_type: str = "fact") -> str:
    """Save a note about the user to long-term memory.

    Use proactively whenever the conversation contains preferences, decisions,
    projects, people, or patterns worth remembering — without waiting for an
    explicit request.

    IMPORTANT: After calling this tool, always call create_linknote immediately
    to connect the new note to related notes, files and directories in the graph.
    A note without links is isolated and hard to discover later.

    If a note with this title already exists, the content is merged automatically.

    Args:
        title: Specific, self-explanatory title (e.g. "Decisão: nginx como proxy do Hughie frontend")
        content: Full content of the note — one concept only, no mixing of topics
        note_type: One of: preference, pattern, project, person, fact
    """
    existing = await brain_store.get_note_by_title(title)
    if existing is not None:
        merged = f"{existing.content}\n\n{content}"
        note = await brain_store.update_note(
            str(existing.id),
            merged,
            note_type=note_type,
            source_kind="agent_request",
        )
        return f"Note updated (merged): '{note.title}' (id: {note.id})"
    note = await brain_store.save_note(title, content, note_type, source_kind="agent_request")
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
    note = await brain_store.update_note(note_id, content, source_kind="agent_request")
    if note is None:
        return f"Note {note_id} not found."
    return f"Note updated: '{note.title}'"


@tool
async def create_linknote(
    focus: str,
    state: Annotated[dict, InjectedState],
) -> str:
    """Create or refresh structured notes with links from the current conversation.

    Call this:
    - Immediately after save_brain_note to connect the new note to the graph.
    - When a discussion introduces new concepts that should be linked to existing memory.
    - When the user asks to "registrar", "anotar" or "lembrar" something.

    The worker reads recent conversation history and extracts notes with links to
    related notes, files and directories. Every note it creates is guaranteed to
    have at least one link.

    Args:
        focus: What specifically to capture (e.g. "decisão de usar pgvector para embeddings").
    """
    session_id = state.get("session_id", "")
    if not session_id:
        return "Error: could not determine session."

    n = await run_consolidation(session_id, hint=focus)
    if n == 0:
        return "Linknote worker finished, but no new note was created."
    return f"Linknote worker finished. {n} note(s) created or updated."


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


@tool
async def list_brain_notes(note_type: str = "") -> str:
    """List all active notes in long-term memory, grouped by type, with link count.

    Use this to get an overview of everything stored in memory, or to find note
    titles before using get_brain_note or explore_brain_graph.

    Args:
        note_type: Optional filter — preference, pattern, project, person, fact. Empty = all.
    """
    from hughie.memory.database import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        query = """
            SELECT n.id, n.title, n.type, n.importance, n.content,
                   COUNT(l.id) AS link_count
            FROM brain_notes n
            LEFT JOIN brain_links l ON l.source_note_id = n.id
            WHERE n.status = 'active'
        """
        params: list = []
        if note_type:
            query += " AND n.type = $1"
            params.append(note_type)
        query += " GROUP BY n.id ORDER BY n.importance DESC, n.updated_at DESC"
        rows = await conn.fetch(query, *params)

    if not rows:
        return "Nenhuma nota encontrada."

    by_type: dict[str, list] = {}
    for r in rows:
        by_type.setdefault(r["type"], []).append(r)

    lines: list[str] = [f"Total: {len(rows)} notas ativas\n"]
    for t, notes in by_type.items():
        lines.append(f"[{t}] — {len(notes)} nota(s)")
        for n in notes:
            links_badge = f" ({n['link_count']} links)" if n["link_count"] > 0 else ""
            preview = n["content"][:90].replace("\n", " ")
            if len(n["content"]) > 90:
                preview += "..."
            lines.append(f"  • {n['title']}{links_badge}")
            lines.append(f"    {preview}")
        lines.append("")

    return "\n".join(lines)


@tool
async def get_brain_note(title: str) -> str:
    """Get the full content and all links of a specific note.

    Returns the note's content, outgoing links (to other notes, files and directories)
    and incoming links (which notes point to this one).

    Args:
        title: Exact or approximate note title (fuzzy match is used as fallback).
    """
    note = await brain_store.get_note_by_title(title)
    if note is None:
        candidates = await brain_store.search_notes_with_distance(title, limit=1, threshold=0.5)
        if not candidates:
            return f"Nota '{title}' não encontrada."
        note, _ = candidates[0]

    out_links = await link_store.get_links_for_notes([note.id], limit=30)
    in_links = await link_store.get_backlinks_for_notes([note.id], limit=20)

    lines = [
        f"[{note.type}] {note.title}  (id: {note.id}, importance: {note.importance:.1f})",
        "",
        note.content,
        "",
    ]

    if out_links:
        lines.append("Links de saída:")
        for lnk in out_links:
            if lnk.target_kind == "note":
                lines.append(f"  --{lnk.relation_type}--> [{lnk.target_note_type or 'note'}] {lnk.target_note_title}")
            else:
                lines.append(f"  --{lnk.relation_type}--> [{lnk.target_kind}] {lnk.target_path}")

    if in_links:
        lines.append("Links de entrada (quem referencia esta nota):")
        for lnk in in_links:
            lines.append(f"  <--{lnk.relation_type}-- {lnk.source_note_title}")

    if not out_links and not in_links:
        lines.append("(nenhum link registrado)")

    return "\n".join(lines)


@tool
async def explore_brain_graph(titles: list[str], depth: int = 2) -> str:
    """Explore the knowledge graph starting from one or more notes.

    Performs a BFS traversal following links in both directions (outgoing and incoming)
    up to the specified depth. Returns each discovered note with its full content and
    connections — useful for understanding how concepts are related.

    Args:
        titles: List of note titles to start from (use list_brain_notes to find titles).
        depth: How many link hops to follow (1–3, default 2). Use 1 for direct neighbours
               only, 2 for two levels of connections, 3 for a broad sweep.
    """
    depth = max(1, min(depth, 3))

    # Resolve titles to note IDs
    start_notes: list[brain_store.BrainNote] = []
    for title in titles:
        note = await brain_store.get_note_by_title(title)
        if note is None:
            candidates = await brain_store.search_notes_with_distance(title, limit=1, threshold=0.5)
            if candidates:
                note, _ = candidates[0]
        if note is not None:
            start_notes.append(note)

    if not start_notes:
        return "Nenhuma nota inicial encontrada. Use list_brain_notes para ver os títulos disponíveis."

    # BFS
    visited: dict[str, dict] = {}  # note_id -> {note, out_links, in_links, hop}
    queue: list[tuple[str, int]] = [(n.id, 0) for n in start_notes]

    while queue:
        note_id, hop = queue.pop(0)
        if note_id in visited or hop > depth:
            continue

        note = await brain_store.get_note_by_id(note_id)
        if note is None or note.status != "active":
            continue

        out_links = await link_store.get_links_for_notes([note_id], limit=20)
        in_links = await link_store.get_backlinks_for_notes([note_id], limit=20)

        visited[note_id] = {"note": note, "out_links": out_links, "in_links": in_links, "hop": hop}

        if hop < depth:
            for lnk in out_links:
                if lnk.target_kind == "note" and lnk.target_note_id and lnk.target_note_id not in visited:
                    queue.append((lnk.target_note_id, hop + 1))
            for lnk in in_links:
                if lnk.source_note_id not in visited:
                    queue.append((lnk.source_note_id, hop + 1))

    if not visited:
        return "Nenhuma nota encontrada no grafo."

    # Format output
    lines = [f"Grafo explorado a partir de: {', '.join(n.title for n in start_notes)}"]
    lines.append(f"Profundidade: {depth} | Notas descobertas: {len(visited)}\n")
    lines.append("=" * 60)

    for hop_level in range(depth + 1):
        nodes_at_level = [v for v in visited.values() if v["hop"] == hop_level]
        if not nodes_at_level:
            continue
        label = "Ponto de partida" if hop_level == 0 else f"Nível {hop_level}"
        lines.append(f"\n{'— ' * 30}")
        lines.append(f"{label} ({len(nodes_at_level)} nota(s))")
        lines.append(f"{'— ' * 30}")

        for entry in nodes_at_level:
            note = entry["note"]
            out = entry["out_links"]
            inc = entry["in_links"]

            lines.append(f"\n[{note.type}] {note.title}  (importance: {note.importance:.1f})")
            lines.append(note.content)

            note_out = [l for l in out if l.target_kind == "note"]
            file_out = [l for l in out if l.target_kind in {"file", "directory"}]
            if note_out:
                lines.append("  → Links para notas:")
                for lnk in note_out:
                    lines.append(f"    --{lnk.relation_type}--> {lnk.target_note_title}")
            if file_out:
                lines.append("  → Links para arquivos/diretórios:")
                for lnk in file_out:
                    path = (lnk.target_path or "")[-60:]
                    lines.append(f"    --{lnk.relation_type}--> [{lnk.target_kind}] ...{path}")
            if inc:
                lines.append("  ← Referenciada por:")
                for lnk in inc:
                    lines.append(f"    <--{lnk.relation_type}-- {lnk.source_note_title}")

    return "\n".join(lines)


BRAIN_TOOLS = [
    save_brain_note,
    search_brain_notes,
    update_brain_note,
    list_brain_notes,
    get_brain_note,
    explore_brain_graph,
    consolidate_memory,
    create_linknote,
]
