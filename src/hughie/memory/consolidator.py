"""
Background memory consolidation worker.

Two trigger modes:
  - Auto:   every N interactions in a session (configured via consolidation_batch_size)
  - Manual: Hughie calls consolidate_memory(hint) to process the last few turns with focus
"""

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

from codex_bridge_sdk import CodexBridgeClient
from google import genai
from google.genai import types as genai_types

from hughie.config import get_settings
from hughie.memory import brain_store, conversation_store, link_store
from hughie.memory.database import get_pool
from hughie.memory.file_reader import classify_path, collect_file_contents, extract_paths

logger = logging.getLogger(__name__)

_RETRY_DELAY_RE = re.compile(r"retry[^\d]*(\d+(?:\.\d+)?)\s*s", re.IGNORECASE)
_MAX_RETRIES = 2


def _parse_retry_delay(exc: Exception) -> float:
    msg = str(exc)
    match = _RETRY_DELAY_RE.search(msg)
    if match:
        return min(float(match.group(1)), 120.0)
    return 60.0


async def _call_with_retry(fn, *args, **kwargs):
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:
            if "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc):
                if attempt < _MAX_RETRIES:
                    delay = _parse_retry_delay(exc)
                    logger.warning(
                        "Consolidation 429 rate limit — retrying in %.0fs (attempt %d/%d)",
                        delay, attempt + 1, _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.warning("Consolidation skipped: rate limit exceeded (quota exhausted)")
                return None
            raise


def _flash_client() -> genai.Client:
    return genai.Client(api_key=get_settings().google_api_key)


def _broker_client() -> CodexBridgeClient:
    settings = get_settings()
    return CodexBridgeClient(base_url=settings.bridge_url, timeout=settings.consolidation_broker_timeout)


def _extract_json_payload(text: str) -> Any:
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("Empty consolidation payload.")

    for candidate in (cleaned, cleaned.removeprefix("```json").removeprefix("```").removesuffix("```").strip()):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    for start_char, end_char in (("{", "}"), ("[", "]")):
        start = cleaned.find(start_char)
        end = cleaned.rfind(end_char)
        if start != -1 and end != -1 and end > start:
            snippet = cleaned[start : end + 1]
            try:
                return json.loads(snippet)
            except json.JSONDecodeError:
                continue

    raise ValueError("Could not parse JSON from consolidation payload.")


async def _generate_via_broker(prompt: str) -> str:
    settings = get_settings()
    client = _broker_client()
    payload = {
        "provider": settings.consolidation_provider,
        "model": settings.consolidation_model,
        "messages": [{"role": "user", "content": prompt}],
    }
    response = await asyncio.to_thread(client.chat, payload)
    text = str(response.get("outputText", "")).strip()
    if not text:
        raise RuntimeError("Broker returned an empty response for consolidation.")
    return text


async def _generate_via_gemini_api(prompt: str, *, response_format: str | None = None) -> str:
    settings = get_settings()
    client = _flash_client()
    config = None
    if response_format == "json":
        config = genai_types.GenerateContentConfig(response_mime_type="application/json")
    response = client.models.generate_content(
        model=settings.consolidation_api_fallback_model,
        contents=prompt,
        config=config,
    )
    return response.text.strip()


async def _generate_text(prompt: str, *, response_format: str | None = None) -> str:
    try:
        return await _generate_via_gemini_api(prompt, response_format=response_format)
    except Exception as exc:
        logger.warning("Consolidation Gemini API failed, falling back to broker: %s", exc)
        return await _generate_via_broker(prompt)


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


def _turn_role_and_content(turn: Any) -> tuple[str, str]:
    if isinstance(turn, dict):
        return str(turn.get("role", "")), str(turn.get("content", ""))
    role = getattr(turn, "role", "")
    content = getattr(turn, "content", "")
    return str(role), str(content)


def _normalize_path(path: str) -> tuple[str | None, str | None]:
    try:
        resolved = str(Path(path).expanduser().resolve())
    except Exception:
        return None, None
    kind = classify_path(resolved)
    if not kind:
        return None, None
    return resolved, kind


def _build_consolidation_prompt(
    conversation_text: str,
    file_contents: dict[str, str],
    *,
    hint: str = "",
) -> str:
    file_section = ""
    if file_contents:
        parts = [f"[Arquivo: {path}]\n{content}" for path, content in file_contents.items()]
        file_section = "\n\nConteúdo dos arquivos mencionados:\n" + "\n\n".join(parts)

    mentioned_paths = extract_paths(conversation_text)
    paths_section = ""
    if mentioned_paths:
        paths_section = "\n\nCaminhos absolutos mencionados:\n" + "\n".join(f"- {path}" for path in mentioned_paths)

    hint_section = f"\n\nFoco especial: {hint}" if hint else ""

    return (
        "Analise esta conversa entre um usuário e seu assistente pessoal Hughie.\n"
        "Crie linknotes úteis e duráveis sobre preferências, projetos, pessoas, decisões técnicas, "
        "arquitetura, fatos importantes ou documentação viva do trabalho.\n"
        f"{hint_section}\n\n"
        "Retorne APENAS um objeto JSON válido no formato:\n"
        "{\n"
        '  "notes": [\n'
        "    {\n"
        '      "titulo": "string",\n'
        '      "conteudo": "string",\n'
        '      "tipo": "preference|pattern|project|person|fact",\n'
        '      "importance": 0.0-1.0,\n'
        '      "links": [\n'
        "        {\n"
        '          "target_kind": "note|file|directory",\n'
        '          "target_title": "string opcional para note",\n'
        '          "target_path": "caminho absoluto opcional para file/directory",\n'
        '          "relation_type": "related_to|depends_on|implemented_by|documented_in|located_in|about",\n'
        '          "weight": 0.0-1.0\n'
        "        }\n"
        "      ]\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Não use markdown. Não explique. Não inclua texto fora do JSON.\n"
        "Crie links para outras notas quando houver um conceito claramente conectado.\n"
        "Crie links para arquivos e diretórios quando caminhos absolutos reais estiverem presentes e forem relevantes.\n\n"
        f"Conversa:\n{conversation_text}"
        f"{paths_section}"
        f"{file_section}"
    )


async def _extract_linknotes(
    conversation_text: str,
    file_contents: dict[str, str],
    *,
    hint: str = "",
) -> list[dict[str, Any]]:
    prompt = _build_consolidation_prompt(conversation_text, file_contents, hint=hint)

    async def _call():
        response_text = await _generate_text(prompt, response_format="json")
        payload = _extract_json_payload(response_text)
        if isinstance(payload, dict):
            notes = payload.get("notes", [])
            return notes if isinstance(notes, list) else []
        if isinstance(payload, list):
            return payload
        return []

    result = await _call_with_retry(_call)
    if result is None:
        return []
    return result if isinstance(result, list) else []


async def _merge_or_rewrite(existing_content: str, new_info: str) -> str:
    prompt = (
        "Você tem uma nota existente e uma nova informação sobre o mesmo tema.\n"
        "Reescreva a nota incorporando a nova informação de forma coesa.\n"
        "Remova redundâncias. Preserve informações importantes. Seja conciso.\n\n"
        f"Nota atual:\n{existing_content}\n\n"
        f"Nova informação:\n{new_info}\n\n"
        "Responda APENAS com o novo conteúdo da nota, sem explicações."
    )

    async def _call():
        return await _generate_text(prompt)

    result = await _call_with_retry(_call)
    if result is None:
        return f"{existing_content}\n\n{new_info}"
    return result


def _normalize_link_candidate(link: dict[str, Any]) -> dict[str, Any] | None:
    target_kind = str(link.get("target_kind") or "").strip().lower()
    relation_type = str(link.get("relation_type") or "related_to").strip() or "related_to"
    weight = float(link.get("weight") or 1.0)

    if target_kind == "note":
        target_title = str(link.get("target_title") or "").strip()
        if not target_title:
            return None
        return {
            "target_kind": "note",
            "target_title": target_title,
            "relation_type": relation_type,
            "weight": weight,
            "evidence": {},
        }

    if target_kind in {"file", "directory"}:
        raw_path = str(link.get("target_path") or "").strip()
        normalized_path, actual_kind = _normalize_path(raw_path)
        if not normalized_path or actual_kind != target_kind:
            return None
        return {
            "target_kind": target_kind,
            "target_path": normalized_path,
            "relation_type": relation_type,
            "weight": weight,
            "evidence": {},
        }

    return None


def _derive_path_links(note: dict[str, Any], conversation_text: str) -> list[dict[str, Any]]:
    merged_text = "\n".join(
        [
            str(note.get("titulo") or ""),
            str(note.get("conteudo") or ""),
            conversation_text,
        ]
    )
    links: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for path in extract_paths(merged_text):
        normalized_path, target_kind = _normalize_path(path)
        if not normalized_path or not target_kind:
            continue
        key = (target_kind, normalized_path)
        if key in seen:
            continue
        seen.add(key)
        links.append(
            {
                "target_kind": target_kind,
                "target_path": normalized_path,
                "relation_type": "related_to",
                "weight": 0.6,
                "evidence": {"derived_from_paths": True},
            }
        )
    return links


async def _process_linknotes(notes: list[dict[str, Any]], conversation_text: str) -> int:
    count = 0
    for note_data in notes:
        title = str(note_data.get("titulo") or "").strip()
        content = str(note_data.get("conteudo") or "").strip()
        note_type = str(note_data.get("tipo") or "fact").strip() or "fact"
        importance = float(note_data.get("importance") or 0.8)

        if not title or not content:
            continue

        exact = await brain_store.get_note_by_title(title)
        similar = []
        if exact is None:
            similar = await brain_store.search_notes_with_distance(title, limit=1, threshold=0.35)
        metadata = {"linknote": True}
        if exact is not None:
            merged = await _merge_or_rewrite(exact.content, content)
            note = await brain_store.update_note(
                str(exact.id),
                merged,
                title=title,
                note_type=note_type,
                importance=max(exact.importance, importance),
                status="active",
                source_kind="auto_worker",
                metadata={**exact.metadata, **metadata},
            )
        elif similar:
            existing, _ = similar[0]
            merged = await _merge_or_rewrite(existing.content, content)
            note = await brain_store.update_note(
                str(existing.id),
                merged,
                title=title,
                note_type=note_type,
                importance=max(existing.importance, importance),
                status="active",
                source_kind="auto_worker",
                metadata={**existing.metadata, **metadata},
            )
        else:
            note = await brain_store.save_note(
                title,
                content,
                note_type,
                importance,
                status="active",
                source_kind="auto_worker",
                metadata=metadata,
            )

        if note is None:
            continue

        raw_links = note_data.get("links", [])
        normalized_links: list[dict[str, Any]] = []
        seen_targets: set[tuple[str, str]] = set()

        if isinstance(raw_links, list):
            for link in raw_links:
                if not isinstance(link, dict):
                    continue
                normalized = _normalize_link_candidate(link)
                if normalized is None:
                    continue
                if normalized["target_kind"] == "note":
                    target_note = await brain_store.ensure_note_by_title(
                        normalized["target_title"],
                        source_kind="auto_worker",
                    )
                    if target_note is None or str(target_note.id) == str(note.id):
                        continue
                    key = ("note", str(target_note.id))
                    if key in seen_targets:
                        continue
                    seen_targets.add(key)
                    normalized_links.append(
                        {
                            "target_kind": "note",
                            "target_note_id": str(target_note.id),
                            "relation_type": normalized["relation_type"],
                            "weight": normalized["weight"],
                            "evidence": normalized["evidence"],
                        }
                    )
                else:
                    key = (normalized["target_kind"], normalized["target_path"])
                    if key in seen_targets:
                        continue
                    seen_targets.add(key)
                    normalized_links.append(normalized)

        for derived in _derive_path_links(note_data, conversation_text):
            key = (derived["target_kind"], derived["target_path"])
            if key in seen_targets:
                continue
            seen_targets.add(key)
            normalized_links.append(derived)

        await link_store.replace_links_for_note(str(note.id), normalized_links, created_by="worker")
        count += 1

    return count


async def run_consolidation(session_id: str, hint: str = "") -> int:
    settings = get_settings()

    if hint:
        turns = await conversation_store.get_recent(session_id, limit=settings.consolidation_context_turns)
    else:
        turns = await _get_unprocessed_turns(session_id)
        if not turns:
            return 0

    lines = []
    for turn in turns:
        role, content = _turn_role_and_content(turn)
        if not content:
            continue
        label = "Usuário" if role == "user" else "Hughie"
        lines.append(f"{label}: {content}")
    conversation_text = "\n".join(lines)

    file_contents = collect_file_contents(conversation_text)
    notes = await _extract_linknotes(conversation_text, file_contents, hint=hint)
    count = await _process_linknotes(notes, conversation_text)

    if not hint:
        await _mark_consolidated(session_id)

    return count


async def maybe_consolidate(session_id: str) -> None:
    settings = get_settings()
    try:
        unprocessed = await _count_unprocessed(session_id)
        if unprocessed >= settings.consolidation_batch_size:
            count = await run_consolidation(session_id)
            if count:
                logger.info("Consolidation: %d linknotes updated for session %s", count, session_id)
    except Exception as exc:
        logger.error("Consolidation error for session %s: %s", session_id, exc)
