"""
Background memory consolidation worker.

Two trigger modes:
  - Auto:   every N interactions in a session (configured via consolidation_batch_size)
  - Manual: Hughie calls consolidate_memory(hint) to process the last few turns with focus

Flow per consolidation run:
  1. Get conversation turns
  2. Fetch context notes (semantic search + graph hubs)
  3. Collect all paths from LLM output + conversation text
  4. SSH-batch-check paths that belong to the local machine
  5. Call LLM with improved prompt (context + single-responsibility rules)
  6. Save notes and links
"""

import asyncio
import json
import logging
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from codex_bridge_sdk import CodexBridgeClient
from google import genai
from google.genai import types as genai_types

from hughie.config import get_settings
from hughie.memory import brain_store, conversation_store, episode_store, link_store
from hughie.prompts import render as render_prompt
from hughie.memory.database import get_pool
from hughie.memory.file_reader import (
    classify_path,
    classify_paths_ssh_batch,
    collect_file_contents,
    extract_paths,
)

logger = logging.getLogger(__name__)

_RETRY_DELAY_RE = re.compile(r"retry[^\d]*(\d+(?:\.\d+)?)\s*s", re.IGNORECASE)
_MAX_RETRIES = 2


# ── Retry helper ──────────────────────────────────────────────────────────────

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


# ── LLM clients ───────────────────────────────────────────────────────────────

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
        return await _generate_via_broker(prompt)
    except Exception as exc:
        logger.warning("Consolidation broker failed, falling back to Gemini API: %s", exc)
        return await _generate_via_gemini_api(prompt, response_format=response_format)


# ── DB helpers ────────────────────────────────────────────────────────────────

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
            SELECT role, content, metadata, created_at FROM conversations
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


async def _get_hub_note_ids(limit: int = 5) -> list[str]:
    """Return IDs of notes with the most outgoing links (graph hubs)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT source_note_id::text AS id
            FROM brain_links
            WHERE target_kind = 'note'
            GROUP BY source_note_id
            ORDER BY COUNT(*) DESC
            LIMIT $1
            """,
            limit,
        )
    return [r["id"] for r in rows]


# ── Context notes (semantic + hubs) ───────────────────────────────────────────

async def _get_context_notes(conversation_text: str) -> list[brain_store.BrainNote]:
    """Fetch up to 10 relevant notes: top-5 semantic + top-5 graph hubs, deduplicated."""
    try:
        semantic = await brain_store.search_notes(
            conversation_text[:2000], limit=5, distance_threshold=0.65
        )
    except Exception as exc:
        logger.warning("Context semantic search failed: %s", exc)
        semantic = []

    try:
        hub_ids = await _get_hub_note_ids(limit=5)
        hubs = await brain_store.get_notes_by_ids(hub_ids)
    except Exception as exc:
        logger.warning("Context hub fetch failed: %s", exc)
        hubs = []

    seen: set[str] = {n.id for n in semantic}
    combined: list[brain_store.BrainNote] = list(semantic)
    for note in hubs:
        if note.id not in seen:
            combined.append(note)
            seen.add(note.id)

    return combined[:10]


# ── Path classification with SSH batch ────────────────────────────────────────

async def _collect_candidate_paths(notes: list[dict[str, Any]], conversation_text: str) -> list[str]:
    """Gather every unique absolute path from LLM output + conversation text."""
    seen: set[str] = set()
    paths: list[str] = []

    def _add(p: str) -> None:
        p = p.strip()
        if p and p not in seen:
            seen.add(p)
            paths.append(p)

    for note in notes:
        for link in note.get("links", []):
            if isinstance(link, dict) and link.get("target_kind") in ("file", "directory"):
                raw = str(link.get("target_path") or "")
                if raw:
                    _add(raw)
        # paths in title/content
        for p in extract_paths(str(note.get("titulo", "")) + " " + str(note.get("conteudo", ""))):
            _add(p)

    for p in extract_paths(conversation_text):
        _add(p)

    return paths


async def _build_path_cache(
    all_paths: list[str],
    local_prefixes: list[str],
    local_host: str,
) -> dict[str, str | None]:
    """
    For each path:
      - Try local filesystem first
      - If not found locally but matches a local_prefix, try SSH batch
    Returns dict[path -> "file" | "directory" | None]
    """
    cache: dict[str, str | None] = {}
    ssh_candidates: list[str] = []

    for path in all_paths:
        kind = classify_path(path)
        if kind:
            cache[path] = kind
        elif any(path.startswith(prefix) for prefix in local_prefixes):
            ssh_candidates.append(path)
        else:
            cache[path] = None

    if ssh_candidates and local_host:
        logger.debug("SSH batch checking %d path(s) on %s", len(ssh_candidates), local_host)
        ssh_results = await classify_paths_ssh_batch(local_host, ssh_candidates)
        for path in ssh_candidates:
            cache[path] = ssh_results.get(path)

    return cache


def _normalize_path_with_cache(
    path: str, path_cache: dict[str, str | None]
) -> tuple[str | None, str | None]:
    try:
        resolved = str(Path(path).expanduser().resolve())
    except Exception:
        return None, None
    kind = path_cache.get(resolved) or path_cache.get(path)
    if not kind:
        kind = classify_path(resolved)
    if not kind:
        return None, None
    return resolved, kind


# ── Prompt ────────────────────────────────────────────────────────────────────

def _build_consolidation_prompt(
    conversation_text: str,
    file_contents: dict[str, str],
    context_notes: list[brain_store.BrainNote],
    *,
    hint: str = "",
) -> str:
    hint_section = f"\n\nFoco especial: {hint}" if hint else ""

    context_section = ""
    if context_notes:
        lines = [
            "## Notas já existentes\n"
            "Use estes títulos EXATOS ao criar links para notas existentes:"
        ]
        for note in context_notes:
            snippet = note.content[:200].replace("\n", " ")
            lines.append(f'  • "{note.title}" [{note.type}] — {snippet}')
        context_section = "\n".join(lines)

    mentioned_paths = extract_paths(conversation_text)
    paths_section = ""
    if mentioned_paths:
        paths_section = "\n\nCaminhos absolutos mencionados:\n" + "\n".join(
            f"- {p}" for p in mentioned_paths
        )

    file_section = ""
    if file_contents:
        parts = [f"[Arquivo: {path}]\n{content}" for path, content in file_contents.items()]
        file_section = "\n\nConteúdo dos arquivos mencionados:\n\n" + "\n\n".join(parts)

    return render_prompt(
        "consolidation",
        hint_section=hint_section,
        context_section=context_section,
        conversation_text=conversation_text,
        paths_section=paths_section,
        file_section=file_section,
    )


# ── LLM extraction ────────────────────────────────────────────────────────────

async def _extract_linknotes(
    conversation_text: str,
    file_contents: dict[str, str],
    context_notes: list[brain_store.BrainNote],
    *,
    hint: str = "",
) -> list[dict[str, Any]]:
    prompt = _build_consolidation_prompt(conversation_text, file_contents, context_notes, hint=hint)

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


async def merge_note_content(existing_content: str, new_info: str) -> str:
    prompt = render_prompt(
        "merge",
        existing_content=existing_content,
        new_info=new_info,
    )

    async def _call():
        return await _generate_text(prompt)

    result = await _call_with_retry(_call)
    if result is None:
        return f"{existing_content}\n\n{new_info}"
    return result


def _build_episode_prompt(
    session_id: str,
    conversation_text: str,
    turns: list[Any],
    note_titles: list[str],
) -> str:
    tool_names: list[str] = []
    for turn in turns:
        metadata = _turn_metadata(turn)
        for name in metadata.get("tool_call_names", []):
            normalized = str(name).strip()
            if normalized and normalized not in tool_names:
                tool_names.append(normalized)

    files = sorted(extract_paths(conversation_text))
    return render_prompt(
        "episode",
        session_id=session_id,
        tool_names=str(tool_names),
        files=str(files),
        note_titles=str(note_titles),
        conversation_text=conversation_text,
    )


async def _extract_episode(
    session_id: str,
    conversation_text: str,
    turns: list[Any],
    note_titles: list[str],
) -> dict[str, Any] | None:
    prompt = _build_episode_prompt(session_id, conversation_text, turns, note_titles)

    async def _call():
        response_text = await _generate_text(prompt, response_format="json")
        payload = _extract_json_payload(response_text)
        return payload if isinstance(payload, dict) else {}

    payload = await _call_with_retry(_call)
    if payload is None:
        return None

    if not payload.get("tempo_total_segundos"):
        payload["tempo_total_segundos"] = _estimate_session_duration_seconds(turns)
    if not payload.get("arquivos_modificados"):
        payload["arquivos_modificados"] = sorted(extract_paths(conversation_text))
    return payload


# ── Link normalisation ────────────────────────────────────────────────────────

def _normalize_link_candidate(
    link: dict[str, Any], path_cache: dict[str, str | None]
) -> dict[str, Any] | None:
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
        normalized_path, actual_kind = _normalize_path_with_cache(raw_path, path_cache)
        if not normalized_path or actual_kind != target_kind:
            return None
        return {
            "target_kind": actual_kind,
            "target_path": normalized_path,
            "relation_type": relation_type,
            "weight": weight,
            "evidence": {},
        }

    return None


def _derive_path_links(
    note: dict[str, Any],
    conversation_text: str,
    path_cache: dict[str, str | None],
) -> list[dict[str, Any]]:
    merged_text = "\n".join([
        str(note.get("titulo") or ""),
        str(note.get("conteudo") or ""),
        conversation_text,
    ])
    links: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for path in extract_paths(merged_text):
        normalized_path, target_kind = _normalize_path_with_cache(path, path_cache)
        if not normalized_path or not target_kind:
            continue
        key = (target_kind, normalized_path)
        if key in seen:
            continue
        seen.add(key)
        links.append({
            "target_kind": target_kind,
            "target_path": normalized_path,
            "relation_type": "related_to",
            "weight": 0.6,
            "evidence": {"derived_from_paths": True},
        })
    return links


# ── Note processing ───────────────────────────────────────────────────────────

def _turn_role_and_content(turn: Any) -> tuple[str, str]:
    if isinstance(turn, Mapping):
        return str(turn.get("role", "")), str(turn.get("content", ""))
    try:
        normalized = dict(turn)
    except Exception:
        normalized = None
    if isinstance(normalized, dict):
        return str(normalized.get("role", "")), str(normalized.get("content", ""))
    role = getattr(turn, "role", "")
    content = getattr(turn, "content", "")
    return str(role), str(content)


def _turn_metadata(turn: Any) -> dict[str, Any]:
    if isinstance(turn, Mapping):
        metadata = turn.get("metadata")
    else:
        try:
            normalized = dict(turn)
        except Exception:
            normalized = None
        metadata = normalized.get("metadata") if isinstance(normalized, dict) else getattr(turn, "metadata", {})
    if isinstance(metadata, str):
        text = metadata.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return metadata if isinstance(metadata, dict) else {}


def _session_has_productive_tool_calls(turns: list[Any]) -> bool:
    for turn in turns:
        metadata = _turn_metadata(turn)
        if metadata.get("had_tool_calls"):
            return True
        if int(metadata.get("tool_message_count") or 0) > 0:
            return True
        if metadata.get("tool_call_names"):
            return True
    return False


def _estimate_session_duration_seconds(turns: list[Any]) -> int | None:
    timestamps = []
    for turn in turns:
        if isinstance(turn, Mapping):
            created_at = turn.get("created_at")
        else:
            try:
                normalized = dict(turn)
            except Exception:
                normalized = None
            created_at = normalized.get("created_at") if isinstance(normalized, dict) else getattr(turn, "created_at", None)
        if created_at is not None:
            timestamps.append(created_at)
    if len(timestamps) < 2:
        return None
    return max(0, int((max(timestamps) - min(timestamps)).total_seconds()))


async def _resolve_note_match(
    title: str,
) -> tuple[brain_store.BrainNote | None, brain_store.BrainNote | None]:
    """Return (exact, fuzzy) for a note title. Safe to run in parallel."""
    exact = await brain_store.get_note_by_title(title)
    if exact is not None:
        return exact, None
    similar = await brain_store.search_notes_with_distance(title, limit=1, threshold=0.35)
    return None, (similar[0][0] if similar else None)


async def _process_linknotes(
    notes: list[dict[str, Any]],
    conversation_text: str,
    path_cache: dict[str, str | None],
) -> tuple[int, list[str]]:
    # ── Filter valid notes ─────────────────────────────────────────────────────
    valid = [
        n for n in notes
        if str(n.get("titulo") or "").strip() and str(n.get("conteudo") or "").strip()
    ]
    if not valid:
        return 0, []

    # ── Phase 1: parallel DB lookups (fast, no LLM) ───────────────────────────
    matches: list[tuple[brain_store.BrainNote | None, brain_store.BrainNote | None]] = list(
        await asyncio.gather(*[
            _resolve_note_match(str(n.get("titulo") or "").strip())
            for n in valid
        ])
    )

    # ── Phase 2: parallel LLM merges (slow — run all at once) ─────────────────
    async def _merge_content(
        note_data: dict[str, Any],
        exact: brain_store.BrainNote | None,
        fuzzy: brain_store.BrainNote | None,
    ) -> str:
        content = str(note_data.get("conteudo") or "").strip()
        existing = exact or fuzzy
        if existing is not None:
            return await merge_note_content(existing.content, content)
        return content

    merged_contents: list[str] = list(await asyncio.gather(*[
        _merge_content(n, ex, fz)
        for n, (ex, fz) in zip(valid, matches)
    ]))

    # ── Phase 3: sequential writes + link resolution ───────────────────────────
    count = 0
    affected_node_ids: list[str] = []
    metadata_base = {"linknote": True}

    for note_data, (exact, fuzzy), merged in zip(valid, matches, merged_contents):
        title = str(note_data.get("titulo") or "").strip()
        note_type = str(note_data.get("tipo") or "fact").strip() or "fact"
        importance = float(note_data.get("importance") or 0.8)

        if exact is not None:
            note = await brain_store.update_note(
                str(exact.id),
                merged,
                title=title,
                note_type=note_type,
                importance=max(exact.importance, importance),
                status="active",
                source_kind="auto_worker",
                metadata={**exact.metadata, **metadata_base},
            )
        elif fuzzy is not None:
            note = await brain_store.update_note(
                str(fuzzy.id),
                merged,
                title=title,
                note_type=note_type,
                importance=max(fuzzy.importance, importance),
                status="active",
                source_kind="auto_worker",
                metadata={**fuzzy.metadata, **metadata_base},
            )
        else:
            note = await brain_store.save_note(
                title,
                merged,
                note_type,
                importance,
                status="active",
                source_kind="auto_worker",
                metadata=metadata_base,
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
                normalized = _normalize_link_candidate(link, path_cache)
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
                    normalized_links.append({
                        "target_kind": "note",
                        "target_note_id": str(target_note.id),
                        "relation_type": normalized["relation_type"],
                        "weight": normalized["weight"],
                        "evidence": normalized["evidence"],
                    })
                else:
                    key = (normalized["target_kind"], normalized["target_path"])
                    if key in seen_targets:
                        continue
                    seen_targets.add(key)
                    normalized_links.append(normalized)

        for derived in _derive_path_links(note_data, conversation_text, path_cache):
            key = (derived["target_kind"], derived["target_path"])
            if key in seen_targets:
                continue
            seen_targets.add(key)
            normalized_links.append(derived)

        await link_store.replace_links_for_note(str(note.id), normalized_links, created_by="worker")
        count += 1
        affected_node_ids.append(str(note.id))

    return count, affected_node_ids


async def _promote_learnings_to_graph(
    learnings: list[Any],
    affected_node_ids: list[str],
) -> list[str]:
    promoted_ids: list[str] = []
    unique_targets = [node_id for node_id in dict.fromkeys(affected_node_ids) if node_id]
    for item in learnings:
        text = str(item).strip()
        if not text:
            continue
        title = f"Aprendizado: {text[:80]}"
        note = await brain_store.create_note(
            title=title,
            content=text,
            note_type="fact",
            importance=1.0,
            status="active",
            source_kind="episode_learning",
            metadata={"episode_learning": True},
            fonte="execucao_real",
            confianca=1.0,
            peso_temporal=1.0,
            criado_por="consolidator",
            metadados={"kind": "episode_learning"},
        )
        promoted_ids.append(str(note.id))
        if unique_targets:
            await link_store.replace_links_for_note(
                str(note.id),
                [
                    {
                        "target_kind": "note",
                        "target_note_id": target_id,
                        "relation_type": "referencia",
                        "tipo_relacao": "referencia",
                        "weight": 1.0,
                        "confianca": 1.0,
                        "fonte": "execucao_real",
                        "evidence": {"promoted_from_learning": True},
                    }
                    for target_id in unique_targets
                    if target_id != str(note.id)
                ],
                created_by="consolidator",
            )
    return promoted_ids


# ── Public API ────────────────────────────────────────────────────────────────

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

    # Fetch context: semantic top-5 + hub top-5
    context_notes = await _get_context_notes(conversation_text)

    # Call LLM
    notes = await _extract_linknotes(conversation_text, file_contents, context_notes, hint=hint)

    # Collect all candidate paths and batch-check them (local + SSH)
    all_paths = await _collect_candidate_paths(notes, conversation_text)
    path_cache = await _build_path_cache(
        all_paths,
        settings.local_machine_path_prefixes,
        settings.local_machine_host,
    )

    # note_titles are extracted from raw LLM output — available before process_linknotes
    note_titles = [str(n.get("titulo") or "").strip() for n in notes if str(n.get("titulo") or "").strip()]
    has_tool_calls = _session_has_productive_tool_calls(turns)

    async def _maybe_extract_episode() -> dict[str, Any] | None:
        if not has_tool_calls:
            return None
        return await _extract_episode(session_id, conversation_text, turns, note_titles)

    # Run note processing and episode extraction in parallel — they don't depend on each other
    (count, affected_node_ids), episode_payload = await asyncio.gather(
        _process_linknotes(notes, conversation_text, path_cache),
        _maybe_extract_episode(),
    )

    if episode_payload:
            promoted_learning_ids = await _promote_learnings_to_graph(
                episode_payload.get("aprendizados", []),
                affected_node_ids,
            )
            combined_node_ids = list(
                dict.fromkeys(
                    [
                        *affected_node_ids,
                        *promoted_learning_ids,
                        *[str(node_id) for node_id in episode_payload.get("node_ids_afetados", []) if str(node_id).strip()],
                    ]
                )
            )
            episode_payload["node_ids_afetados"] = combined_node_ids
            episode = await episode_store.create_episode(session_id, episode_payload)
            await episode_store.link_episode_to_graph(episode.id, combined_node_ids)
            logger.info(
                "Consolidation created structured episode %s for session %s with %d affected node(s)",
                episode.id,
                session_id,
                len(combined_node_ids),
            )

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
        logger.exception("Consolidation error for session %s: %s", session_id, exc)
