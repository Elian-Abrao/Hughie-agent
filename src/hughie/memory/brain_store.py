import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime

from hughie.memory.database import get_pool
from hughie.memory.embeddings import embed_document, embed_query


@dataclass
class BrainNote:
    id: str
    title: str
    content: str
    type: str
    importance: float
    created_at: datetime
    updated_at: datetime


async def save_note(title: str, content: str, note_type: str = "fact", importance: float = 1.0) -> BrainNote:
    embedding = embed_document(f"{title}\n{content}")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO brain_notes (title, content, type, embedding, importance)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, title, content, type, importance, created_at, updated_at
            """,
            title, content, note_type, embedding, importance,
        )
    return BrainNote(**dict(row))


async def update_note(note_id: str, content: str) -> BrainNote | None:
    embedding = embed_document(content)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE brain_notes
            SET content = $1, embedding = $2, updated_at = now()
            WHERE id = $3
            RETURNING id, title, content, type, importance, created_at, updated_at
            """,
            content, embedding, uuid.UUID(note_id),
        )
    if row is None:
        return None
    return BrainNote(**dict(row))


async def delete_note(note_id: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM brain_notes WHERE id = $1",
            uuid.UUID(note_id),
        )
    return result == "DELETE 1"


async def search_notes(query: str, limit: int = 5) -> list[BrainNote]:
    embedding = embed_query(query)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, content, type, importance, created_at, updated_at
            FROM brain_notes
            ORDER BY embedding <=> $1
            LIMIT $2
            """,
            embedding, limit,
        )
    return [BrainNote(**dict(r)) for r in rows]


async def search_notes_with_distance(
    query: str, limit: int = 3, threshold: float = 0.35
) -> list[tuple[BrainNote, float]]:
    """Search notes returning only those within the similarity threshold."""
    embedding = embed_query(query)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, content, type, importance, created_at, updated_at,
                   (embedding <=> $1) AS distance
            FROM brain_notes
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> $1
            LIMIT $2
            """,
            embedding, limit,
        )
    results = []
    for r in rows:
        d = dict(r)
        distance = d.pop("distance")
        if distance < threshold:
            results.append((BrainNote(**d), distance))
    return results


async def list_notes(limit: int = 50) -> list[BrainNote]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, content, type, importance, created_at, updated_at
            FROM brain_notes
            ORDER BY updated_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [BrainNote(**dict(r)) for r in rows]


# Sync wrappers for use outside async contexts
def save_note_sync(title: str, content: str, note_type: str = "fact", importance: float = 1.0) -> BrainNote:
    return asyncio.run(save_note(title, content, note_type, importance))


def search_notes_sync(query: str, limit: int = 5) -> list[BrainNote]:
    return asyncio.run(search_notes(query, limit))
