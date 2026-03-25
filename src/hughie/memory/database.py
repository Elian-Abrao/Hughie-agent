import asyncio
import asyncpg
from pgvector.asyncpg import register_vector

from hughie.config import get_settings
from hughie.memory.migrations import DDL

_pool: asyncpg.Pool | None = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    await register_vector(conn)


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=1,
            max_size=10,
            init=_init_connection,
        )
    return _pool


async def run_migrations() -> None:
    settings = get_settings()
    # Cria a extensão vector em uma conexão simples antes de inicializar o pool
    conn = await asyncpg.connect(settings.database_url)
    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    finally:
        await conn.close()

    # Agora o pool pode ser criado com register_vector sem erro
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(DDL)


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def run_migrations_sync() -> None:
    asyncio.run(run_migrations())
