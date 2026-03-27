from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from hughie.memory import brain_graph, brain_store, embeddings, link_store
from hughie.memory.database import get_pool

logger = logging.getLogger(__name__)

GRAPH_HOPS = 2


@dataclass
class RAGResult:
    note: brain_store.BrainNote
    semantic_relevance: float
    score: float
    origin: str
    hop_distance: int
    source_note_id: str | None
    relation_type: str | None
    task_context: str

    def as_metadata(self) -> dict[str, Any]:
        return {
            "id": self.note.id,
            "title": self.note.title,
            "type": self.note.type,
            "fonte": self.note.fonte,
            "confianca": self.note.confianca,
            "peso_temporal": self.note.peso_temporal,
            "origin": self.origin,
            "hop_distance": self.hop_distance,
            "source_note_id": self.source_note_id,
            "relation_type": self.relation_type,
            "semantic_relevance": round(self.semantic_relevance, 4),
            "score": round(self.score, 4),
        }


def embed_query(text: str) -> list[float]:
    return embeddings.embed_query(text)


async def semantic_search(query_embedding: list[float], top_k: int) -> list[dict[str, Any]]:
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
            ORDER BY embedding <=> $1::vector, confianca DESC, peso_temporal DESC
            LIMIT $2
            """,
            query_embedding,
            top_k,
        )
    candidates = []
    for row in rows:
        data = dict(row)
        distance = float(data.pop("distance"))
        note = brain_store._note_from_row(data)
        semantic_relevance = max(0.0, 1.0 - distance)
        candidates.append(
            {
                "note": note,
                "distance": distance,
                "semantic_relevance": semantic_relevance,
                "origin": "semantic_seed",
                "hop_distance": 0,
                "source_note_id": None,
                "relation_type": None,
            }
        )
    logger.info("RAG semantic search returned %d seed note(s)", len(candidates))
    return candidates


async def expand_by_graph(node_ids: list[str], hops: int = GRAPH_HOPS) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    seen: set[str] = set(node_ids)
    seeds = {candidate_id: 1.0 for candidate_id in node_ids}

    for seed_id in node_ids:
        neighbors = await brain_graph.get_neighbors(seed_id, hops=hops)
        outgoing = await link_store.get_links_for_notes([seed_id], limit=200)
        incoming = await link_store.get_backlinks_for_notes([seed_id], limit=200)
        link_map: dict[str, tuple[str | None, float, int]] = {}

        for link in outgoing:
            if link.target_kind == "note" and link.target_note_id:
                link_map[link.target_note_id] = (
                    link.tipo_relacao or link.relation_type,
                    max(0.1, min(1.0, link.confianca)),
                    1,
                )
        for link in incoming:
            link_map[link.source_note_id] = (
                link.tipo_relacao or link.relation_type,
                max(0.1, min(1.0, link.confianca)),
                1,
            )

        for neighbor in neighbors:
            if neighbor.id in seen:
                continue
            seen.add(neighbor.id)
            relation_type, link_confidence, hop_distance = link_map.get(
                neighbor.id,
                ("related_to", 0.6, min(hops, 2)),
            )
            semantic_relevance = max(0.05, seeds.get(seed_id, 0.5) * link_confidence * (0.9**hop_distance))
            expanded.append(
                {
                    "note": neighbor,
                    "distance": None,
                    "semantic_relevance": semantic_relevance,
                    "origin": "graph_expansion",
                    "hop_distance": hop_distance,
                    "source_note_id": seed_id,
                    "relation_type": relation_type,
                }
            )

    logger.info("RAG graph expansion returned %d neighbor note(s)", len(expanded))
    return expanded


def rank_results(candidates: list[dict[str, Any]], task_context: str = "") -> list[RAGResult]:
    ranked: list[RAGResult] = []
    for candidate in candidates:
        note: brain_store.BrainNote = candidate["note"]
        semantic_relevance = max(0.0, float(candidate.get("semantic_relevance") or 0.0))
        score = semantic_relevance * max(0.0, note.confianca) * max(0.0, note.peso_temporal)
        if task_context:
            lowered = task_context.lower()
            if note.title.lower() in lowered or note.type.lower() in lowered:
                score *= 1.05
        ranked.append(
            RAGResult(
                note=note,
                semantic_relevance=semantic_relevance,
                score=score,
                origin=str(candidate.get("origin") or "semantic_seed"),
                hop_distance=int(candidate.get("hop_distance") or 0),
                source_note_id=candidate.get("source_note_id"),
                relation_type=candidate.get("relation_type"),
                task_context=task_context,
            )
        )

    ranked.sort(key=lambda item: (item.score, item.note.confianca, item.note.peso_temporal), reverse=True)
    logger.info("RAG ranking produced %d ranked note(s)", len(ranked))
    return ranked


async def retrieve(query: str, task_context: str, top_k: int = 10) -> list[RAGResult]:
    search_text = "\n".join(part for part in [query.strip(), task_context.strip()] if part.strip())
    if not search_text:
        return []

    query_embedding = embed_query(search_text)
    seeds = await semantic_search(query_embedding, top_k=max(top_k, 5))
    seed_ids = [candidate["note"].id for candidate in seeds]
    expanded = await expand_by_graph(seed_ids, hops=GRAPH_HOPS) if seed_ids else []

    dedup: dict[str, dict[str, Any]] = {}
    for candidate in seeds + expanded:
        note_id = candidate["note"].id
        current = dedup.get(note_id)
        if current is None or float(candidate["semantic_relevance"]) > float(current["semantic_relevance"]):
            dedup[note_id] = candidate

    ranked = rank_results(list(dedup.values()), task_context=task_context)[:top_k]
    for result in ranked:
        await brain_store.refresh_temporal_weight(result.note.id, target_weight=1.0)
    logger.info("RAG retrieve finished with %d result(s) for query=%r", len(ranked), query)
    return ranked


def format_context(ranked_results: list[RAGResult]) -> str:
    if not ranked_results:
        return ""

    lines = ["Contexto recuperado do grafo e memória semântica:"]
    for index, result in enumerate(ranked_results, start=1):
        metadata = result.as_metadata()
        lines.append(
            f"{index}. [{result.note.type}] {result.note.title}: {result.note.content}\n"
            f"   origem={metadata['origin']} fonte={metadata['fonte']} "
            f"confianca={metadata['confianca']} peso_temporal={metadata['peso_temporal']} "
            f"score={metadata['score']} hop={metadata['hop_distance']}"
        )
    return "\n".join(lines)


async def retrieve_context_v2(query: str, task_context: str, top_k: int = 10) -> dict[str, Any]:
    ranked = await retrieve(query=query, task_context=task_context, top_k=top_k)
    return {
        "results": ranked,
        "context": format_context(ranked),
    }


async def _main_async(query: str) -> None:
    payload = await retrieve_context_v2(query=query, task_context=query, top_k=10)
    for result in payload["results"]:
        print(json.dumps(result.as_metadata(), ensure_ascii=False))
        print(result.note.content)
        print("---")


def main() -> None:
    import sys

    query = " ".join(sys.argv[1:]).strip()
    if not query:
        raise SystemExit("Usage: python -m hughie.memory.rag \"sua query\"")
    asyncio.run(_main_async(query))


if __name__ == "__main__":
    main()
