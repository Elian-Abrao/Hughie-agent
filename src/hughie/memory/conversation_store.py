import asyncio
from dataclasses import dataclass
from datetime import datetime

from hughie.memory.database import get_pool
from hughie.memory.embeddings import embed_document


@dataclass
class ConversationTurn:
    id: str
    session_id: str
    role: str
    content: str
    created_at: datetime


async def save_turn(session_id: str, role: str, content: str) -> ConversationTurn:
    embedding = embed_document(content)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO conversations (session_id, role, content, embedding)
            VALUES ($1, $2, $3, $4)
            RETURNING id, session_id, role, content, created_at
            """,
            session_id, role, content, embedding,
        )
    return ConversationTurn(**dict(row))


async def get_recent(session_id: str, limit: int = 20) -> list[ConversationTurn]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, session_id, role, content, created_at
            FROM conversations
            WHERE session_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            session_id, limit,
        )
    return list(reversed([ConversationTurn(**dict(r)) for r in rows]))


def save_turn_sync(session_id: str, role: str, content: str) -> ConversationTurn:
    return asyncio.run(save_turn(session_id, role, content))


def get_recent_sync(session_id: str, limit: int = 20) -> list[ConversationTurn]:
    return asyncio.run(get_recent(session_id, limit))


async def list_sessions(limit: int = 50) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                session_id,
                COUNT(*) AS message_count,
                MAX(created_at) AS last_at,
                (
                    SELECT content FROM conversations c2
                    WHERE c2.session_id = c.session_id
                    ORDER BY created_at DESC LIMIT 1
                ) AS last_message
            FROM conversations c
            GROUP BY session_id
            ORDER BY last_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [dict(r) for r in rows]
