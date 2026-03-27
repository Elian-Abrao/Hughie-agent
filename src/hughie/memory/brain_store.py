import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from hughie.memory.database import get_pool
from hughie.memory.embeddings import embed_document, embed_query


@dataclass
class BrainNote:
    id: str
    title: str
    content: str
    type: str
    importance: float
    status: str
    source_kind: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


def _note_from_row(row) -> BrainNote:
    data = dict(row)
    if "id" in data:
        data["id"] = str(data["id"])
    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        data["metadata"] = {}
    return BrainNote(**data)


async def save_note(
    title: str,
    content: str,
    note_type: str = "fact",
    importance: float = 1.0,
    *,
    status: str = "active",
    source_kind: str = "auto_worker",
    metadata: dict[str, Any] | None = None,
) -> BrainNote:
    embedding = embed_document(f"{title}\n{content}")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO brain_notes (
                title, content, type, embedding, importance, status, source_kind, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
            RETURNING
                id, title, content, type, importance, status, source_kind, metadata,
                created_at, updated_at
            """,
            title,
            content,
            note_type,
            embedding,
            importance,
            status,
            source_kind,
            json.dumps(metadata or {}),
        )
    return _note_from_row(row)


async def update_note(
    note_id: str,
    content: str,
    *,
    title: str | None = None,
    note_type: str | None = None,
    importance: float | None = None,
    status: str | None = None,
    source_kind: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> BrainNote | None:
    embedding = embed_document(f"{title or ''}\n{content}".strip())
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE brain_notes
            SET
                title = COALESCE($1, title),
                content = $2,
                type = COALESCE($3, type),
                importance = COALESCE($4, importance),
                status = COALESCE($5, status),
                source_kind = COALESCE($6, source_kind),
                metadata = COALESCE($7::jsonb, metadata),
                embedding = $8,
                updated_at = now()
            WHERE id = $9
            RETURNING
                id, title, content, type, importance, status, source_kind, metadata,
                created_at, updated_at
            """,
            title,
            content,
            note_type,
            importance,
            status,
            source_kind,
            json.dumps(metadata) if metadata is not None else None,
            embedding,
            uuid.UUID(note_id),
        )
    if row is None:
        return None
    return _note_from_row(row)


async def get_note_by_id(note_id: str) -> BrainNote | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                id, title, content, type, importance, status, source_kind, metadata,
                created_at, updated_at
            FROM brain_notes
            WHERE id = $1
            """,
            uuid.UUID(note_id),
        )
    if row is None:
        return None
    return _note_from_row(row)


async def get_note_by_title(title: str) -> BrainNote | None:
    normalized = title.strip().lower()
    if not normalized:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                id, title, content, type, importance, status, source_kind, metadata,
                created_at, updated_at
            FROM brain_notes
            WHERE lower(title) = $1
            LIMIT 1
            """,
            normalized,
        )
    if row is None:
        return None
    return _note_from_row(row)


async def ensure_note_by_title(
    title: str,
    *,
    note_type: str = "fact",
    source_kind: str = "auto_worker",
) -> BrainNote | None:
    existing = await get_note_by_title(title)
    if existing is not None:
        return existing
    cleaned = title.strip()
    if not cleaned:
        return None
    return await save_note(
        cleaned,
        f"Stub note created for '{cleaned}'.",
        note_type,
        0.2,
        status="stub",
        source_kind=source_kind,
        metadata={"auto_stub": True},
    )


async def delete_note(note_id: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM brain_notes WHERE id = $1",
            uuid.UUID(note_id),
        )
    return result == "DELETE 1"


async def search_notes(
    query: str, limit: int = 5, distance_threshold: float = 0.5
) -> list[BrainNote]:
    embedding = embed_query(query)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                id, title, content, type, importance, status, source_kind, metadata,
                created_at, updated_at
            FROM brain_notes
            WHERE embedding IS NOT NULL
              AND status = 'active'
              AND (embedding <=> $1::vector) < $3
            ORDER BY embedding <=> $1::vector, importance DESC, updated_at DESC
            LIMIT $2
            """,
            embedding,
            limit,
            distance_threshold,
        )
    return [_note_from_row(r) for r in rows]


async def search_notes_with_distance(
    query: str, limit: int = 3, threshold: float = 0.35
) -> list[tuple[BrainNote, float]]:
    """Search notes returning only those within the similarity threshold."""
    embedding = embed_query(query)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                id, title, content, type, importance, status, source_kind, metadata,
                created_at, updated_at,
                (embedding <=> $1::vector) AS distance
            FROM brain_notes
            WHERE embedding IS NOT NULL
              AND status = 'active'
              AND (embedding <=> $1::vector) < $3
            ORDER BY embedding <=> $1::vector, importance DESC, updated_at DESC
            LIMIT $2
            """,
            embedding,
            limit,
            threshold,
        )
    results = []
    for row in rows:
        data = dict(row)
        distance = data.pop("distance")
        results.append((_note_from_row(data), distance))
    return results


async def get_notes_by_ids(note_ids: list[str]) -> list[BrainNote]:
    if not note_ids:
        return []
    uuids = [uuid.UUID(nid) for nid in note_ids]
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                id, title, content, type, importance, status, source_kind, metadata,
                created_at, updated_at
            FROM brain_notes
            WHERE id = ANY($1::uuid[])
            """,
            uuids,
        )
    return [_note_from_row(r) for r in rows]


async def list_notes(limit: int = 50) -> list[BrainNote]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                id, title, content, type, importance, status, source_kind, metadata,
                created_at, updated_at
            FROM brain_notes
            ORDER BY updated_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [_note_from_row(r) for r in rows]


# Sync wrappers for use outside async contexts
def save_note_sync(title: str, content: str, note_type: str = "fact", importance: float = 1.0) -> BrainNote:
    return asyncio.run(save_note(title, content, note_type, importance))


def search_notes_sync(query: str, limit: int = 5) -> list[BrainNote]:
    return asyncio.run(search_notes(query, limit))
