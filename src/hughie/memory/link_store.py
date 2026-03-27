import uuid
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from hughie.memory.database import get_pool


@dataclass
class BrainLink:
    id: str
    source_note_id: str
    source_note_title: str | None
    target_kind: str
    target_note_id: str | None
    target_note_title: str | None
    target_note_content: str | None
    target_note_type: str | None
    target_path: str | None
    relation_type: str
    weight: float
    evidence: dict[str, Any]
    created_by: str
    created_at: datetime
    updated_at: datetime


def _link_from_row(row) -> BrainLink:
    data = dict(row)
    for key in ("id", "source_note_id", "target_note_id"):
        if data.get(key) is not None:
            data[key] = str(data[key])
    evidence = data.get("evidence")
    if not isinstance(evidence, dict):
        data["evidence"] = {}
    return BrainLink(**data)


async def replace_links_for_note(
    source_note_id: str,
    links: list[dict[str, Any]],
    *,
    created_by: str = "worker",
) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM brain_links WHERE source_note_id = $1",
                uuid.UUID(source_note_id),
            )

            inserted = 0
            for link in links:
                target_kind = str(link.get("target_kind") or "").strip()
                relation_type = str(link.get("relation_type") or "related_to").strip() or "related_to"
                weight = float(link.get("weight") or 1.0)
                evidence = link.get("evidence") if isinstance(link.get("evidence"), dict) else {}

                target_note_id = link.get("target_note_id")
                target_path = link.get("target_path")

                if target_kind == "note" and target_note_id:
                    await conn.execute(
                        """
                        INSERT INTO brain_links (
                            source_note_id, target_kind, target_note_id,
                            relation_type, weight, evidence, created_by
                        )
                        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
                        """,
                        uuid.UUID(source_note_id),
                        target_kind,
                        uuid.UUID(str(target_note_id)),
                        relation_type,
                        weight,
                        json.dumps(evidence),
                        created_by,
                    )
                    inserted += 1
                elif target_kind in {"file", "directory"} and target_path:
                    await conn.execute(
                        """
                        INSERT INTO brain_links (
                            source_note_id, target_kind, target_path,
                            relation_type, weight, evidence, created_by
                        )
                        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
                        """,
                        uuid.UUID(source_note_id),
                        target_kind,
                        str(target_path),
                        relation_type,
                        weight,
                        json.dumps(evidence),
                        created_by,
                    )
                    inserted += 1
            return inserted


async def get_backlinks_for_notes(target_note_ids: list[str], limit: int = 20) -> list[BrainLink]:
    """Get all note-to-note links pointing TO the given notes (incoming links)."""
    if not target_note_ids:
        return []
    target_ids = [uuid.UUID(str(nid)) for nid in target_note_ids]
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                l.id,
                l.source_note_id,
                s.title AS source_note_title,
                l.target_kind,
                l.target_note_id,
                t.title AS target_note_title,
                t.content AS target_note_content,
                t.type AS target_note_type,
                l.target_path,
                l.relation_type,
                l.weight,
                l.evidence,
                l.created_by,
                l.created_at,
                l.updated_at
            FROM brain_links l
            JOIN brain_notes s ON s.id = l.source_note_id
            LEFT JOIN brain_notes t ON t.id = l.target_note_id
            WHERE l.target_note_id = ANY($1::uuid[])
            ORDER BY l.weight DESC
            LIMIT $2
            """,
            target_ids,
            limit,
        )
    return [_link_from_row(row) for row in rows]


async def list_all_links(limit: int = 1000) -> list[BrainLink]:
    """Get all links for graph visualization."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                l.id,
                l.source_note_id,
                s.title AS source_note_title,
                l.target_kind,
                l.target_note_id,
                t.title AS target_note_title,
                t.content AS target_note_content,
                t.type AS target_note_type,
                l.target_path,
                l.relation_type,
                l.weight,
                l.evidence,
                l.created_by,
                l.created_at,
                l.updated_at
            FROM brain_links l
            JOIN brain_notes s ON s.id = l.source_note_id
            LEFT JOIN brain_notes t ON t.id = l.target_note_id
            ORDER BY l.weight DESC
            LIMIT $1
            """,
            limit,
        )
    return [_link_from_row(row) for row in rows]


async def get_links_for_notes(source_note_ids: list[str], limit: int = 12) -> list[BrainLink]:
    if not source_note_ids:
        return []

    pool = await get_pool()
    source_ids = [uuid.UUID(str(note_id)) for note_id in source_note_ids]
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                l.id,
                l.source_note_id,
                s.title AS source_note_title,
                l.target_kind,
                l.target_note_id,
                t.title AS target_note_title,
                t.content AS target_note_content,
                t.type AS target_note_type,
                l.target_path,
                l.relation_type,
                l.weight,
                l.evidence,
                l.created_by,
                l.created_at,
                l.updated_at
            FROM brain_links l
            JOIN brain_notes s ON s.id = l.source_note_id
            LEFT JOIN brain_notes t ON t.id = l.target_note_id
            WHERE l.source_note_id = ANY($1::uuid[])
            ORDER BY l.weight DESC, l.updated_at DESC
            LIMIT $2
            """,
            source_ids,
            limit,
        )
    return [_link_from_row(row) for row in rows]
