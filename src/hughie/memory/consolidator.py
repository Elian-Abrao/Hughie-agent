"""
Background memory consolidation worker.

Two trigger modes:
  - Auto:   every N interactions in a session (configured via consolidation_batch_size)
  - Manual: Hughie calls consolidate_memory(hint) to process the last few turns with focus
"""

import asyncio
import json
import logging

from google import genai
from google.genai import types as genai_types

from hughie.config import get_settings
from hughie.memory import brain_store, conversation_store
from hughie.memory.database import get_pool
from hughie.memory.file_reader import collect_file_contents

logger = logging.getLogger(__name__)


def _flash_client() -> genai.Client:
    return genai.Client(api_key=get_settings().google_api_key)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def _count_unprocessed(session_id: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            SELECT COUNT(*) FROM conversations
            WHERE session_id = $1
              AND created_at > COALESCE(
                  (SELECT last_processed_at FROM consolidation_state WHERE session_id = $1),
                  '1970-01-01'::timestamptz
              )
            """,
            session_id,
        )


async def _get_unprocessed_turns(session_id: str) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT role, content FROM conversations
            WHERE session_id = $1
              AND created_at > COALESCE(
                  (SELECT last_processed_at FROM consolidation_state WHERE session_id = $1),
                  '1970-01-01'::timestamptz
              )
            ORDER BY created_at ASC
            """,
            session_id,
        )


async def _mark_consolidated(session_id: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO consolidation_state (session_id, last_processed_at)
            VALUES ($1, now())
            ON CONFLICT (session_id) DO UPDATE SET last_processed_at = now()
            """,
            session_id,
        )


# ---------------------------------------------------------------------------
# Gemini Flash helpers
# ---------------------------------------------------------------------------

async def _extract_memories(
    conversation_text: str,
    file_contents: dict[str, str],
    hint: str = "",
) -> list[dict]:
    settings = get_settings()
    client = _flash_client()

    file_section = ""
    if file_contents:
        parts = [f"[Arquivo: {p}]\n{c}" for p, c in file_contents.items()]
        file_section = "\n\nConteúdo dos arquivos mencionados:\n" + "\n\n".join(parts)

    hint_section = f"\n\nFoco especial: {hint}" if hint else ""

    prompt = (
        "Analise esta conversa entre um usuário e seu assistente pessoal Hughie.\n"
        "Identifique informações importantes sobre o usuário, seus projetos, preferências, "
        "padrões de comportamento, decisões técnicas ou documentação de projetos."
        f"{hint_section}\n\n"
        "Para cada informação relevante, retorne um objeto JSON com:\n"
        '- "titulo": título descritivo do tópico\n'
        '- "conteudo": a informação detalhada\n'
        '- "tipo": um de: preference, pattern, project, person, fact\n\n'
        "Retorne APENAS um array JSON válido. Se não houver nada relevante, retorne [].\n\n"
        f"Conversa:\n{conversation_text}"
        f"{file_section}"
    )

    response = client.models.generate_content(
        model=settings.flash_model,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )

    try:
        return json.loads(response.text)
    except Exception:
        return []


async def _merge_or_rewrite(existing_content: str, new_info: str) -> str:
    settings = get_settings()
    client = _flash_client()

    prompt = (
        "Você tem uma nota existente e uma nova informação sobre o mesmo tema.\n"
        "Reescreva a nota incorporando a nova informação de forma coesa.\n"
        "Remova redundâncias. Preserve informações importantes. Seja conciso.\n\n"
        f"Nota atual:\n{existing_content}\n\n"
        f"Nova informação:\n{new_info}\n\n"
        "Responda APENAS com o novo conteúdo da nota, sem explicações."
    )

    response = client.models.generate_content(
        model=settings.flash_model,
        contents=prompt,
    )
    return response.text.strip()


# ---------------------------------------------------------------------------
# Core consolidation logic
# ---------------------------------------------------------------------------

async def _process_memories(memories: list[dict]) -> int:
    count = 0
    for memory in memories:
        titulo = memory.get("titulo", "").strip()
        conteudo = memory.get("conteudo", "").strip()
        tipo = memory.get("tipo", "fact")

        if not titulo or not conteudo:
            continue

        similar = await brain_store.search_notes_with_distance(titulo, limit=1, threshold=0.35)

        if similar:
            existing, _ = similar[0]
            merged = await _merge_or_rewrite(existing.content, conteudo)
            await brain_store.update_note(str(existing.id), merged)
        else:
            await brain_store.save_note(titulo, conteudo, tipo)

        count += 1
    return count


async def run_consolidation(session_id: str, hint: str = "") -> int:
    """
    Run consolidation for a session.

    - hint="": auto mode — reads unprocessed turns, marks them as consolidated after
    - hint="...": manual mode — reads last N turns with focus, does NOT mark as consolidated
    """
    settings = get_settings()

    if hint:
        turns = await conversation_store.get_recent(session_id, limit=settings.consolidation_context_turns)
    else:
        turns = await _get_unprocessed_turns(session_id)
        if not turns:
            return 0

    lines = []
    for turn in turns:
        role = "Usuário" if turn["role"] == "user" else "Hughie"
        lines.append(f"{role}: {turn['content']}")
    conversation_text = "\n".join(lines)

    file_contents = collect_file_contents(conversation_text)
    memories = await _extract_memories(conversation_text, file_contents, hint)
    count = await _process_memories(memories)

    if not hint:
        await _mark_consolidated(session_id)

    return count


async def maybe_consolidate(session_id: str) -> None:
    """Auto-trigger: fire consolidation if enough new turns have accumulated."""
    settings = get_settings()
    try:
        unprocessed = await _count_unprocessed(session_id)
        if unprocessed >= settings.consolidation_batch_size:
            n = await run_consolidation(session_id)
            if n:
                logger.info("Consolidation: %d notes updated for session %s", n, session_id)
    except Exception as exc:
        logger.error("Consolidation error for session %s: %s", session_id, exc)
