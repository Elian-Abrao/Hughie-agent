import json
import logging
import uuid
from collections import deque
from typing import Any

from hughie.memory import brain_store, link_store
from hughie.memory.database import get_pool

logger = logging.getLogger(__name__)


async def get_neighbors(node_id: str, hops: int = 1) -> list[brain_store.BrainNote]:
    hops = max(1, hops)
    visited: set[str] = {node_id}
    frontier: deque[tuple[str, int]] = deque([(node_id, 0)])
    discovered: list[str] = []

    while frontier:
        current_id, depth = frontier.popleft()
        if depth >= hops:
            continue

        outgoing = await link_store.get_links_for_notes([current_id], limit=100)
        incoming = await link_store.get_backlinks_for_notes([current_id], limit=100)
        for link in outgoing:
            if link.target_kind == "note" and link.target_note_id and link.target_note_id not in visited:
                visited.add(link.target_note_id)
                discovered.append(link.target_note_id)
                frontier.append((link.target_note_id, depth + 1))
        for link in incoming:
            if link.source_note_id not in visited:
                visited.add(link.source_note_id)
                discovered.append(link.source_note_id)
                frontier.append((link.source_note_id, depth + 1))

    logger.info("Fetched %d neighbor(s) for node %s with hops=%d", len(discovered), node_id, hops)
    return await brain_store.get_notes_by_ids(discovered)


async def get_subgraph(node_ids: list[str]) -> dict[str, Any]:
    notes = await brain_store.get_notes_by_ids(node_ids)
    links = await link_store.list_all_links(limit=5000)
    valid_ids = {note.id for note in notes}
    filtered_links = [
        link
        for link in links
        if link.source_note_id in valid_ids
        and link.target_kind == "note"
        and link.target_note_id in valid_ids
    ]
    logger.info("Built induced subgraph with %d node(s) and %d edge(s)", len(notes), len(filtered_links))
    return {"nodes": notes, "edges": filtered_links}


async def merge_nodes(node_id_a: str, node_id_b: str) -> brain_store.BrainNote | None:
    note_a = await brain_store.get_note_by_id(node_id_a)
    note_b = await brain_store.get_note_by_id(node_id_b)
    if note_a is None or note_b is None:
        return None

    winner_payload = brain_store.resolve_conflict(
        note_a,
        {
            "title": note_b.title,
            "content": note_b.content,
            "note_type": note_b.type,
            "importance": max(note_a.importance, note_b.importance),
            "status": note_a.status if note_a.status == "active" else note_b.status,
            "source_kind": note_b.source_kind,
            "metadata": {**note_a.metadata, **note_b.metadata},
            "fonte": note_b.fonte,
            "confianca": note_b.confianca,
            "peso_temporal": max(note_a.peso_temporal, note_b.peso_temporal),
            "criado_por": note_a.criado_por,
            "metadados": {**note_a.metadados, **note_b.metadados},
        },
    )

    merged_history = list(note_a.historico) + list(note_b.historico) + [
        {"merged_from": node_id_a, "title": note_a.title, "content": note_a.content},
        {"merged_from": node_id_b, "title": note_b.title, "content": note_b.content},
    ]

    merged_note = await brain_store.update_note(
        note_a.id,
        str(winner_payload["content"]),
        title=str(winner_payload["title"]),
        note_type=str(winner_payload["note_type"]),
        importance=float(winner_payload["importance"]),
        status=str(winner_payload["status"]),
        source_kind=str(winner_payload["source_kind"]),
        metadata=winner_payload["metadata"],
        fonte=str(winner_payload["fonte"]),
        confianca=float(winner_payload["confianca"]),
        peso_temporal=float(winner_payload["peso_temporal"]),
        criado_por=str(winner_payload["criado_por"]),
        metadados={**winner_payload["metadados"], "merged_history": merged_history},
    )
    if merged_note is None:
        return None

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE brain_links
                SET source_note_id = $1
                WHERE source_note_id = $2
                """,
                uuid.UUID(node_id_a),
                uuid.UUID(node_id_b),
            )
            await conn.execute(
                """
                UPDATE brain_links
                SET target_note_id = $1
                WHERE target_note_id = $2
                """,
                uuid.UUID(node_id_a),
                uuid.UUID(node_id_b),
            )
            await conn.execute(
                "DELETE FROM brain_notes WHERE id = $1",
                uuid.UUID(node_id_b),
            )

    logger.info("Merged node %s into %s", node_id_b, node_id_a)
    return await brain_store.get_note_by_id(node_id_a)


async def mark_stale(node_id: str) -> brain_store.BrainNote | None:
    note = await brain_store.get_note_by_id(node_id)
    if note is None:
        return None
    logger.info("Marking note %s as stale", node_id)
    return await brain_store.update_note(
        note_id=node_id,
        content=note.content,
        title=note.title,
        note_type=note.type,
        importance=note.importance,
        status="stale",
        source_kind=note.source_kind,
        metadata=note.metadata,
        fonte=note.fonte,
        confianca=note.confianca,
        peso_temporal=min(note.peso_temporal, 0.1),
        criado_por=note.criado_por,
        metadados={**note.metadados, "stale": True},
    )


async def garbage_collect() -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT n.id
            FROM brain_notes n
            LEFT JOIN brain_links outgoing ON outgoing.source_note_id = n.id
            LEFT JOIN brain_links incoming ON incoming.target_note_id = n.id
            WHERE n.peso_temporal < 0.05
            GROUP BY n.id
            HAVING COUNT(outgoing.id) = 0 AND COUNT(incoming.id) = 0
            """
        )
        if not rows:
            logger.info("Garbage collection found no orphan stale nodes")
            return 0
        ids = [row["id"] for row in rows]
        await conn.execute(
            "DELETE FROM brain_notes WHERE id = ANY($1::uuid[])",
            ids,
        )
    logger.info("Garbage collection removed %d note(s)", len(rows))
    return len(rows)
