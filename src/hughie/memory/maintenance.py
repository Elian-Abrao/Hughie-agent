from __future__ import annotations

import logging
from typing import Any

from hughie.memory import brain_graph, brain_store
from hughie.memory.database import get_pool

logger = logging.getLogger(__name__)


async def run_decay() -> int:
    logger.info("Maintenance: starting temporal decay")
    updated = await brain_store.decay_temporal_weight(days_without_access=7, decay_factor=0.1)
    logger.info("Maintenance: temporal decay updated %d note(s)", updated)
    return updated


async def run_garbage_collection() -> int:
    logger.info("Maintenance: starting garbage collection")
    removed = await brain_graph.garbage_collect()
    logger.info("Maintenance: garbage collection removed %d note(s)", removed)
    return removed


def _history_candidate(note: brain_store.BrainNote, entry: dict[str, Any]) -> dict[str, Any] | None:
    source = brain_store._normalize_source(str(entry.get("fonte") or ""))
    if brain_store.SOURCE_PRIORITY[source] <= brain_store.SOURCE_PRIORITY[note.fonte]:
        return None
    content = str(entry.get("content") or "").strip()
    if not content:
        return None
    return {
        "title": str(entry.get("title") or note.title),
        "content": content,
        "note_type": str(entry.get("type") or note.type),
        "importance": float(entry.get("importance") or note.importance),
        "status": str(entry.get("status") or note.status),
        "source_kind": str(entry.get("source_kind") or note.source_kind),
        "metadata": entry.get("metadata") if isinstance(entry.get("metadata"), dict) else note.metadata,
        "fonte": source,
        "confianca": float(entry.get("confianca") or brain_store.SOURCE_PRIORITY[source]),
        "peso_temporal": float(entry.get("peso_temporal") or note.peso_temporal),
        "criado_por": str(entry.get("criado_por") or note.criado_por),
        "metadados": entry.get("metadados") if isinstance(entry.get("metadados"), dict) else note.metadados,
    }


async def run_conflict_resolution(limit: int = 500) -> int:
    logger.info("Maintenance: starting conflict resolution scan")
    resolved = 0
    notes = await brain_store.list_notes(limit=limit)
    for note in notes:
        best_candidate = None
        for entry in note.historico:
            candidate = _history_candidate(note, entry)
            if candidate is None:
                continue
            if (
                best_candidate is None
                or brain_store.SOURCE_PRIORITY[candidate["fonte"]] > brain_store.SOURCE_PRIORITY[best_candidate["fonte"]]
            ):
                best_candidate = candidate

        if best_candidate is None:
            continue

        await brain_store.update_note(
            note.id,
            best_candidate["content"],
            title=best_candidate["title"],
            note_type=best_candidate["note_type"],
            importance=best_candidate["importance"],
            status=best_candidate["status"],
            source_kind=best_candidate["source_kind"],
            metadata=best_candidate["metadata"],
            fonte=best_candidate["fonte"],
            confianca=best_candidate["confianca"],
            peso_temporal=best_candidate["peso_temporal"],
            criado_por=best_candidate["criado_por"],
            metadados=best_candidate["metadados"],
        )
        resolved += 1

    logger.info("Maintenance: conflict resolution updated %d note(s)", resolved)
    return resolved


async def run_all() -> dict[str, int]:
    logger.info("Maintenance: starting full run")
    try:
        decay = await run_decay()
        gc = await run_garbage_collection()
        conflict = await run_conflict_resolution()
    except Exception:
        logger.exception("Maintenance: full run failed")
        raise

    result = {"decayed": decay, "garbage_collected": gc, "conflicts_resolved": conflict}
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO maintenance_runs (decayed, garbage_collected, conflicts_resolved)
            VALUES ($1, $2, $3)
            """,
            decay,
            gc,
            conflict,
        )
    logger.info("Maintenance: full run finished %s", result)
    return result
