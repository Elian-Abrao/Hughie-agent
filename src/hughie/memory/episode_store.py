from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from hughie.memory import brain_store, link_store
from hughie.memory.database import get_pool
from hughie.memory.embeddings import embed_document, embed_query

logger = logging.getLogger(__name__)


def _normalize_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return [text]
        return parsed if isinstance(parsed, list) else []
    return []


@dataclass
class Episode:
    id: str
    session_id: str
    created_at: datetime
    tarefa: str
    resultado: str
    tempo_total_segundos: int | None
    arquivos_modificados: list[Any]
    decisoes_tomadas: list[Any]
    erros_encontrados: list[Any]
    aprendizados: list[Any]
    node_ids_afetados: list[Any]


def _episode_from_row(row: dict[str, Any]) -> Episode:
    return Episode(
        id=str(row["id"]),
        session_id=str(row["session_id"]),
        created_at=row["created_at"],
        tarefa=str(row["tarefa"]),
        resultado=str(row["resultado"]),
        tempo_total_segundos=row.get("tempo_total_segundos"),
        arquivos_modificados=_normalize_json_list(row.get("arquivos_modificados")),
        decisoes_tomadas=_normalize_json_list(row.get("decisoes_tomadas")),
        erros_encontrados=_normalize_json_list(row.get("erros_encontrados")),
        aprendizados=_normalize_json_list(row.get("aprendizados")),
        node_ids_afetados=_normalize_json_list(row.get("node_ids_afetados")),
    )


def _episode_embedding_text(data: dict[str, Any]) -> str:
    return "\n".join(
        part
        for part in [
            str(data.get("tarefa") or "").strip(),
            str(data.get("resultado") or "").strip(),
            "\n".join(str(item) for item in _normalize_json_list(data.get("aprendizados"))),
            "\n".join(str(item) for item in _normalize_json_list(data.get("decisoes_tomadas"))),
        ]
        if part
    )


async def create_episode(session_id: str, data: dict[str, Any]) -> Episode:
    embedding_text = _episode_embedding_text(data)
    embedding = embed_document(embedding_text) if embedding_text else None
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO episodes (
                session_id,
                tarefa,
                resultado,
                tempo_total_segundos,
                arquivos_modificados,
                decisoes_tomadas,
                erros_encontrados,
                aprendizados,
                node_ids_afetados,
                embedding
            )
            VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb, $8::jsonb, $9::jsonb, $10)
            RETURNING
                id, session_id, created_at, tarefa, resultado, tempo_total_segundos,
                arquivos_modificados, decisoes_tomadas, erros_encontrados,
                aprendizados, node_ids_afetados
            """,
            session_id,
            str(data.get("tarefa") or "").strip() or "Sessão produtiva",
            str(data.get("resultado") or "").strip() or "Sem resumo informado.",
            data.get("tempo_total_segundos"),
            json.dumps(_normalize_json_list(data.get("arquivos_modificados"))),
            json.dumps(_normalize_json_list(data.get("decisoes_tomadas"))),
            json.dumps(_normalize_json_list(data.get("erros_encontrados"))),
            json.dumps(_normalize_json_list(data.get("aprendizados"))),
            json.dumps(_normalize_json_list(data.get("node_ids_afetados"))),
            embedding,
        )
    episode = _episode_from_row(dict(row))
    logger.info("Created episode %s for session %s", episode.id, session_id)
    return episode


async def search_similar_episodes(query: str, top_k: int = 5) -> list[Episode]:
    query_embedding = embed_query(query)
    return await search_similar_episodes_by_embedding(query_embedding, top_k=top_k)


async def search_similar_episodes_by_embedding(
    query_embedding: list[float],
    top_k: int = 5,
) -> list[Episode]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                id, session_id, created_at, tarefa, resultado, tempo_total_segundos,
                arquivos_modificados, decisoes_tomadas, erros_encontrados,
                aprendizados, node_ids_afetados
            FROM episodes
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> $1::vector, created_at DESC
            LIMIT $2
            """,
            query_embedding,
            top_k,
        )
    return [_episode_from_row(dict(row)) for row in rows]


async def get_episode(episode_id: str) -> Episode | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                id, session_id, created_at, tarefa, resultado, tempo_total_segundos,
                arquivos_modificados, decisoes_tomadas, erros_encontrados,
                aprendizados, node_ids_afetados
            FROM episodes
            WHERE id = $1
            """,
            episode_id,
        )
    return _episode_from_row(dict(row)) if row else None


async def list_episodes(limit: int = 20) -> list[Episode]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                id, session_id, created_at, tarefa, resultado, tempo_total_segundos,
                arquivos_modificados, decisoes_tomadas, erros_encontrados,
                aprendizados, node_ids_afetados
            FROM episodes
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [_episode_from_row(dict(row)) for row in rows]


async def link_episode_to_graph(episode_id: str, node_ids: list[str]) -> str | None:
    episode = await get_episode(episode_id)
    if episode is None:
        return None

    requested_node_ids = [str(node_id) for node_id in node_ids if str(node_id).strip()]
    existing_notes = await brain_store.get_notes_by_ids(requested_node_ids)
    valid_node_ids = [str(note.id) for note in existing_notes]
    if not valid_node_ids:
        return None

    title = f"Episódio {episode.created_at.date()} {episode.session_id[:8]}"
    content = f"Tarefa: {episode.tarefa}\nResultado: {episode.resultado}"
    episode_note = await brain_store.create_note(
        title=title,
        content=content,
        note_type="fact",
        importance=1.0,
        status="active",
        source_kind="episode_store",
        metadata={"episode_id": episode.id, "episode_link": True},
        fonte="execucao_real",
        confianca=1.0,
        peso_temporal=1.0,
        criado_por="episode_store",
        metadados={"episode_id": episode.id, "kind": "episode_summary"},
    )

    links = [
        {
            "target_kind": "note",
            "target_note_id": node_id,
            "relation_type": "referencia",
            "tipo_relacao": "referencia",
            "weight": 1.0,
            "confianca": 1.0,
            "fonte": "execucao_real",
            "evidence": {"episode_id": episode.id},
        }
        for node_id in valid_node_ids
        if node_id != str(episode_note.id)
    ]
    await link_store.replace_links_for_note(str(episode_note.id), links, created_by="episode_store")

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE episodes
            SET node_ids_afetados = $2::jsonb
            WHERE id = $1
            """,
            episode_id,
            json.dumps(valid_node_ids),
        )

    logger.info(
        "Linked episode %s to %d graph node(s) via note %s",
        episode_id,
        len(valid_node_ids),
        episode_note.id,
    )
    return str(episode_note.id)
