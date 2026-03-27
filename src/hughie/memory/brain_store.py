import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from hughie.memory.database import get_pool
from hughie.memory.embeddings import embed_document, embed_query

logger = logging.getLogger(__name__)

SOURCE_PRIORITY = {
    "execucao_real": 1.0,
    "inferencia": 0.7,
    "crawling": 0.5,
    "input_manual": 0.3,
}
DEFAULT_SOURCE = "input_manual"
DEFAULT_CONFIDENCE = SOURCE_PRIORITY[DEFAULT_SOURCE]
DEFAULT_TEMPORAL_WEIGHT = 1.0


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
    fonte: str
    confianca: float
    peso_temporal: float
    criado_por: str
    ultima_atualizacao: datetime
    historico: list[dict[str, Any]]
    metadados: dict[str, Any]
    created_at: datetime
    updated_at: datetime


def _normalize_source(source: str | None) -> str:
    normalized = (source or "").strip().lower()
    return normalized if normalized in SOURCE_PRIORITY else DEFAULT_SOURCE


def _normalize_confidence(source: str, confidence: float | None) -> float:
    if confidence is None:
        return SOURCE_PRIORITY[source]
    return max(0.0, min(1.0, float(confidence)))


def _normalize_temporal_weight(weight: float | None) -> float:
    if weight is None:
        return DEFAULT_TEMPORAL_WEIGHT
    return max(0.0, min(1.0, float(weight)))


def _normalize_dict(value: Any, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return dict(fallback or {})
        if isinstance(parsed, dict):
            return parsed
    return dict(fallback or {})


def _normalize_history(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _note_from_row(row) -> BrainNote:
    data = dict(row)
    if "id" in data:
        data["id"] = str(data["id"])

    metadata = _normalize_dict(data.get("metadata"))
    metadados = _normalize_dict(data.get("metadados"), metadata)

    source_kind = str(data.get("source_kind") or "").strip() or metadata.get("source_kind", "auto_worker")
    fonte = _normalize_source(data.get("fonte") or metadata.get("fonte"))
    data["source_kind"] = source_kind
    data["metadata"] = metadata
    data["metadados"] = metadados
    data["fonte"] = fonte
    data["confianca"] = _normalize_confidence(fonte, data.get("confianca"))
    data["peso_temporal"] = _normalize_temporal_weight(data.get("peso_temporal"))
    data["criado_por"] = str(data.get("criado_por") or source_kind or "system")
    data["historico"] = _normalize_history(data.get("historico"))
    data["ultima_atualizacao"] = data.get("ultima_atualizacao") or data.get("updated_at")
    return BrainNote(**data)


def resolve_conflict(
    existing_note: BrainNote | dict[str, Any],
    incoming_payload: dict[str, Any],
) -> dict[str, Any]:
    existing_source = _normalize_source(
        existing_note.fonte if isinstance(existing_note, BrainNote) else existing_note.get("fonte")
    )
    incoming_source = _normalize_source(str(incoming_payload.get("fonte") or DEFAULT_SOURCE))
    existing_priority = SOURCE_PRIORITY[existing_source]
    incoming_priority = SOURCE_PRIORITY[incoming_source]

    merged = dict(incoming_payload)
    if incoming_priority >= existing_priority:
        merged["fonte"] = incoming_source
        merged["confianca"] = _normalize_confidence(incoming_source, incoming_payload.get("confianca"))
        return merged

    if isinstance(existing_note, BrainNote):
        merged["title"] = existing_note.title
        merged["content"] = existing_note.content
        merged["note_type"] = existing_note.type
        merged["importance"] = existing_note.importance
        merged["status"] = existing_note.status
        merged["source_kind"] = existing_note.source_kind
        merged["metadata"] = existing_note.metadata
        merged["fonte"] = existing_note.fonte
        merged["confianca"] = existing_note.confianca
        merged["peso_temporal"] = existing_note.peso_temporal
        merged["criado_por"] = existing_note.criado_por
        merged["metadados"] = existing_note.metadados
    else:
        merged["fonte"] = existing_source
        merged["confianca"] = _normalize_confidence(existing_source, existing_note.get("confianca"))
    return merged


def _history_entry(note: BrainNote) -> dict[str, Any]:
    return {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "title": note.title,
        "content": note.content,
        "type": note.type,
        "importance": note.importance,
        "status": note.status,
        "source_kind": note.source_kind,
        "metadata": note.metadata,
        "fonte": note.fonte,
        "confianca": note.confianca,
        "peso_temporal": note.peso_temporal,
        "criado_por": note.criado_por,
        "ultima_atualizacao": note.ultima_atualizacao.isoformat() if note.ultima_atualizacao else None,
        "metadados": note.metadados,
        "updated_at": note.updated_at.isoformat() if note.updated_at else None,
    }


async def create_note(
    title: str,
    content: str,
    note_type: str = "fact",
    importance: float = 1.0,
    *,
    status: str = "active",
    source_kind: str = "auto_worker",
    metadata: dict[str, Any] | None = None,
    fonte: str = DEFAULT_SOURCE,
    confianca: float | None = None,
    peso_temporal: float = DEFAULT_TEMPORAL_WEIGHT,
    criado_por: str | None = None,
    metadados: dict[str, Any] | None = None,
) -> BrainNote:
    normalized_source = _normalize_source(fonte)
    normalized_confidence = _normalize_confidence(normalized_source, confianca)
    normalized_weight = _normalize_temporal_weight(peso_temporal)
    normalized_metadata = metadata or {}
    normalized_metadados = metadados or normalized_metadata
    embedding = embed_document(f"{title}\n{content}")

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO brain_notes (
                title, content, type, embedding, importance, status, source_kind, metadata,
                fonte, confianca, peso_temporal, criado_por, ultima_atualizacao, historico, metadados
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8::jsonb,
                $9, $10, $11, $12, now(), $13::jsonb, $14::jsonb
            )
            RETURNING
                id, title, content, type, importance, status, source_kind, metadata,
                fonte, confianca, peso_temporal, criado_por, ultima_atualizacao, historico, metadados,
                created_at, updated_at
            """,
            title,
            content,
            note_type,
            embedding,
            importance,
            status,
            source_kind,
            json.dumps(normalized_metadata),
            normalized_source,
            normalized_confidence,
            normalized_weight,
            criado_por or source_kind,
            json.dumps([]),
            json.dumps(normalized_metadados),
        )
    return _note_from_row(row)


async def save_note(
    title: str,
    content: str,
    note_type: str = "fact",
    importance: float = 1.0,
    *,
    status: str = "active",
    source_kind: str = "auto_worker",
    metadata: dict[str, Any] | None = None,
    fonte: str = DEFAULT_SOURCE,
    confianca: float | None = None,
    peso_temporal: float = DEFAULT_TEMPORAL_WEIGHT,
    criado_por: str | None = None,
    metadados: dict[str, Any] | None = None,
) -> BrainNote:
    return await create_note(
        title,
        content,
        note_type,
        importance,
        status=status,
        source_kind=source_kind,
        metadata=metadata,
        fonte=fonte,
        confianca=confianca,
        peso_temporal=peso_temporal,
        criado_por=criado_por,
        metadados=metadados,
    )


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
    fonte: str | None = None,
    confianca: float | None = None,
    peso_temporal: float | None = None,
    criado_por: str | None = None,
    metadados: dict[str, Any] | None = None,
) -> BrainNote | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            current_row = await conn.fetchrow(
                """
                SELECT
                    id, title, content, type, importance, status, source_kind, metadata,
                    fonte, confianca, peso_temporal, criado_por, ultima_atualizacao, historico, metadados,
                    created_at, updated_at
                FROM brain_notes
                WHERE id = $1
                FOR UPDATE
                """,
                uuid.UUID(note_id),
            )
            if current_row is None:
                return None

            current_note = _note_from_row(current_row)
            payload = resolve_conflict(
                current_note,
                {
                    "title": title or current_note.title,
                    "content": content,
                    "note_type": note_type or current_note.type,
                    "importance": importance if importance is not None else current_note.importance,
                    "status": status or current_note.status,
                    "source_kind": source_kind or current_note.source_kind,
                    "metadata": metadata if metadata is not None else current_note.metadata,
                    "fonte": fonte or current_note.fonte,
                    "confianca": confianca if confianca is not None else current_note.confianca,
                    "peso_temporal": peso_temporal if peso_temporal is not None else current_note.peso_temporal,
                    "criado_por": criado_por or current_note.criado_por,
                    "metadados": metadados if metadados is not None else current_note.metadados,
                },
            )
            normalized_source = _normalize_source(payload.get("fonte"))
            normalized_confidence = _normalize_confidence(normalized_source, payload.get("confianca"))
            normalized_weight = _normalize_temporal_weight(payload.get("peso_temporal"))
            history = list(current_note.historico)
            history.append(_history_entry(current_note))

            new_title = str(payload.get("title") or current_note.title)
            embedding = embed_document(f"{new_title}\n{content}".strip())

            row = await conn.fetchrow(
                """
                UPDATE brain_notes
                SET
                    title = $1,
                    content = $2,
                    type = $3,
                    importance = $4,
                    status = $5,
                    source_kind = $6,
                    metadata = $7::jsonb,
                    embedding = $8,
                    updated_at = now(),
                    fonte = $9,
                    confianca = $10,
                    peso_temporal = $11,
                    criado_por = $12,
                    ultima_atualizacao = now(),
                    historico = $13::jsonb,
                    metadados = $14::jsonb
                WHERE id = $15
                RETURNING
                    id, title, content, type, importance, status, source_kind, metadata,
                    fonte, confianca, peso_temporal, criado_por, ultima_atualizacao, historico, metadados,
                    created_at, updated_at
                """,
                new_title,
                content,
                str(payload.get("note_type") or current_note.type),
                float(payload.get("importance") or current_note.importance),
                str(payload.get("status") or current_note.status),
                str(payload.get("source_kind") or current_note.source_kind),
                json.dumps(payload.get("metadata") or current_note.metadata),
                embedding,
                normalized_source,
                normalized_confidence,
                normalized_weight,
                str(payload.get("criado_por") or current_note.criado_por),
                json.dumps(history),
                json.dumps(payload.get("metadados") or current_note.metadados),
                uuid.UUID(note_id),
            )
    return _note_from_row(row)


async def get_note(note_id: str) -> BrainNote | None:
    return await get_note_by_id(note_id)


async def get_note_by_id(note_id: str) -> BrainNote | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                id, title, content, type, importance, status, source_kind, metadata,
                fonte, confianca, peso_temporal, criado_por, ultima_atualizacao, historico, metadados,
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
                fonte, confianca, peso_temporal, criado_por, ultima_atualizacao, historico, metadados,
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
        fonte="inferencia",
        confianca=0.2,
        peso_temporal=0.3,
        criado_por=source_kind,
        metadados={"auto_stub": True},
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
                fonte, confianca, peso_temporal, criado_por, ultima_atualizacao, historico, metadados,
                created_at, updated_at
            FROM brain_notes
            WHERE embedding IS NOT NULL
              AND status = 'active'
              AND (embedding <=> $1::vector) < $3
            ORDER BY embedding <=> $1::vector, confianca DESC, peso_temporal DESC, importance DESC, updated_at DESC
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
    embedding = embed_query(query)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                id, title, content, type, importance, status, source_kind, metadata,
                fonte, confianca, peso_temporal, criado_por, ultima_atualizacao, historico, metadados,
                created_at, updated_at,
                (embedding <=> $1::vector) AS distance
            FROM brain_notes
            WHERE embedding IS NOT NULL
              AND status = 'active'
              AND (embedding <=> $1::vector) < $3
            ORDER BY embedding <=> $1::vector, confianca DESC, peso_temporal DESC, importance DESC, updated_at DESC
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
                fonte, confianca, peso_temporal, criado_por, ultima_atualizacao, historico, metadados,
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
                fonte, confianca, peso_temporal, criado_por, ultima_atualizacao, historico, metadados,
                created_at, updated_at
            FROM brain_notes
            ORDER BY ultima_atualizacao DESC, updated_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [_note_from_row(r) for r in rows]


async def decay_temporal_weight(days_without_access: int = 7, decay_factor: float = 0.1) -> int:
    threshold = datetime.now(timezone.utc) - timedelta(days=days_without_access)
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE brain_notes
            SET
                peso_temporal = GREATEST(0.0, peso_temporal * $1),
                updated_at = now()
            WHERE ultima_atualizacao < $2
            """,
            max(0.0, 1.0 - decay_factor),
            threshold,
        )
    updated = int(result.split()[-1])
    logger.info("Temporal decay applied to %d note(s)", updated)
    return updated


async def refresh_temporal_weight(note_id: str, target_weight: float = 1.0) -> BrainNote | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE brain_notes
            SET
                peso_temporal = $1,
                ultima_atualizacao = now(),
                updated_at = now()
            WHERE id = $2
            RETURNING
                id, title, content, type, importance, status, source_kind, metadata,
                fonte, confianca, peso_temporal, criado_por, ultima_atualizacao, historico, metadados,
                created_at, updated_at
            """,
            _normalize_temporal_weight(target_weight),
            uuid.UUID(note_id),
        )
    if row is None:
        return None
    logger.info("Temporal weight refreshed for note %s", note_id)
    return _note_from_row(row)


# Sync wrappers for use outside async contexts
def save_note_sync(title: str, content: str, note_type: str = "fact", importance: float = 1.0) -> BrainNote:
    return asyncio.run(save_note(title, content, note_type, importance))


def search_notes_sync(query: str, limit: int = 5) -> list[BrainNote]:
    return asyncio.run(search_notes(query, limit))
