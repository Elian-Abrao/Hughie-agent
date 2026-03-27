import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from hughie.memory import rag


@dataclass
class FakeNote:
    id: str
    title: str
    content: str
    type: str = "fact"
    importance: float = 1.0
    status: str = "active"
    source_kind: str = "worker"
    metadata: dict | None = None
    fonte: str = "input_manual"
    confianca: float = 0.3
    peso_temporal: float = 1.0
    criado_por: str = "worker"
    ultima_atualizacao: object = datetime.now(timezone.utc)
    historico: list | None = None
    metadados: dict | None = None
    created_at: object = datetime.now(timezone.utc)
    updated_at: object = datetime.now(timezone.utc)


def test_semantic_search_returns_results(monkeypatch):
    note = FakeNote(id="n1", title="Modulo X", content="Detalhes do modulo X")

    async def fake_semantic_search(query_embedding, top_k):
        return [
            {
                "note": note,
                "distance": 0.1,
                "semantic_relevance": 0.9,
                "origin": "semantic_seed",
                "hop_distance": 0,
                "source_note_id": None,
                "relation_type": None,
            }
        ]

    monkeypatch.setattr(rag, "semantic_search", fake_semantic_search)
    monkeypatch.setattr(rag, "expand_by_graph", AsyncMock(return_value=[]))
    monkeypatch.setattr(rag.brain_store, "refresh_temporal_weight", AsyncMock(return_value=note))
    monkeypatch.setattr(rag, "embed_query", lambda text: [0.0] * 768)

    results = asyncio.run(rag.retrieve("modulo x", "contexto modulo x", top_k=5))

    assert len(results) == 1
    assert results[0].note.id == "n1"


def test_graph_expansion_finds_neighbors(monkeypatch):
    seed = FakeNote(id="seed", title="Seed", content="Seed")
    neighbor = FakeNote(id="neighbor", title="Neighbor", content="Neighbor")

    async def fake_semantic_search(query_embedding, top_k):
        return [
            {
                "note": seed,
                "distance": 0.2,
                "semantic_relevance": 0.8,
                "origin": "semantic_seed",
                "hop_distance": 0,
                "source_note_id": None,
                "relation_type": None,
            }
        ]

    async def fake_expand_by_graph(node_ids, hops=2):
        return [
            {
                "note": neighbor,
                "distance": None,
                "semantic_relevance": 0.5,
                "origin": "graph_expansion",
                "hop_distance": 1,
                "source_note_id": "seed",
                "relation_type": "depende_de",
            }
        ]

    monkeypatch.setattr(rag, "semantic_search", fake_semantic_search)
    monkeypatch.setattr(rag, "expand_by_graph", fake_expand_by_graph)
    monkeypatch.setattr(rag.brain_store, "refresh_temporal_weight", AsyncMock(return_value=neighbor))
    monkeypatch.setattr(rag, "embed_query", lambda text: [0.0] * 768)

    results = asyncio.run(rag.retrieve("seed", "seed contexto", top_k=5))

    ids = [result.note.id for result in results]
    assert "seed" in ids
    assert "neighbor" in ids


def test_ranking_prioritizes_high_confidence():
    low = FakeNote(id="low", title="Low", content="low", confianca=0.3, peso_temporal=1.0)
    high = FakeNote(id="high", title="High", content="high", confianca=1.0, peso_temporal=1.0)

    ranked = rag.rank_results(
        [
            {
                "note": low,
                "semantic_relevance": 0.9,
                "origin": "semantic_seed",
                "hop_distance": 0,
                "source_note_id": None,
                "relation_type": None,
            },
            {
                "note": high,
                "semantic_relevance": 0.8,
                "origin": "semantic_seed",
                "hop_distance": 0,
                "source_note_id": None,
                "relation_type": None,
            },
        ],
        task_context="",
    )

    assert ranked[0].note.id == "high"


def test_temporal_weight_refreshed_after_retrieval(monkeypatch):
    note = FakeNote(id="n1", title="Modulo X", content="Detalhes do modulo X")
    refresh_mock = AsyncMock(return_value=note)

    async def fake_semantic_search(query_embedding, top_k):
        return [
            {
                "note": note,
                "distance": 0.1,
                "semantic_relevance": 0.9,
                "origin": "semantic_seed",
                "hop_distance": 0,
                "source_note_id": None,
                "relation_type": None,
            }
        ]

    monkeypatch.setattr(rag, "semantic_search", fake_semantic_search)
    monkeypatch.setattr(rag, "expand_by_graph", AsyncMock(return_value=[]))
    monkeypatch.setattr(rag.brain_store, "refresh_temporal_weight", refresh_mock)
    monkeypatch.setattr(rag, "embed_query", lambda text: [0.0] * 768)

    asyncio.run(rag.retrieve("modulo x", "contexto modulo x", top_k=5))

    refresh_mock.assert_awaited_once_with("n1", target_weight=1.0)
