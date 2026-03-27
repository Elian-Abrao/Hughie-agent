import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock

from hughie.memory import brain_graph


@dataclass
class FakeNote:
    id: str
    title: str = "Title"
    content: str = "Content"
    type: str = "fact"
    importance: float = 1.0
    status: str = "active"
    source_kind: str = "worker"
    metadata: dict | None = None
    fonte: str = "input_manual"
    confianca: float = 0.3
    peso_temporal: float = 1.0
    criado_por: str = "worker"
    ultima_atualizacao: object = None
    historico: list | None = None
    metadados: dict | None = None
    created_at: object = None
    updated_at: object = None


@dataclass
class FakeLink:
    source_note_id: str
    target_kind: str
    target_note_id: str | None = None


def test_get_neighbors_returns_discovered_notes(monkeypatch):
    monkeypatch.setattr(
        brain_graph.link_store,
        "get_links_for_notes",
        AsyncMock(return_value=[FakeLink(source_note_id="a", target_kind="note", target_note_id="b")]),
    )
    monkeypatch.setattr(
        brain_graph.link_store,
        "get_backlinks_for_notes",
        AsyncMock(return_value=[FakeLink(source_note_id="c", target_kind="note", target_note_id="a")]),
    )
    monkeypatch.setattr(
        brain_graph.brain_store,
        "get_notes_by_ids",
        AsyncMock(side_effect=lambda ids: [FakeNote(id=value) for value in ids]),
    )

    neighbors = asyncio.run(brain_graph.get_neighbors("a", hops=1))

    assert [note.id for note in neighbors] == ["b", "c"]


def test_get_subgraph_filters_to_induced_edges(monkeypatch):
    monkeypatch.setattr(
        brain_graph.brain_store,
        "get_notes_by_ids",
        AsyncMock(return_value=[FakeNote(id="a"), FakeNote(id="b")]),
    )
    monkeypatch.setattr(
        brain_graph.link_store,
        "list_all_links",
        AsyncMock(
            return_value=[
                SimpleNamespace(source_note_id="a", target_kind="note", target_note_id="b"),
                SimpleNamespace(source_note_id="a", target_kind="note", target_note_id="z"),
            ]
        ),
    )

    subgraph = asyncio.run(brain_graph.get_subgraph(["a", "b"]))

    assert len(subgraph["nodes"]) == 2
    assert len(subgraph["edges"]) == 1
    assert subgraph["edges"][0].target_note_id == "b"


def test_mark_stale_lowers_weight_and_sets_status(monkeypatch):
    note = FakeNote(id="a", peso_temporal=0.9, metadados={})
    monkeypatch.setattr(brain_graph.brain_store, "get_note_by_id", AsyncMock(return_value=note))
    update_mock = AsyncMock(return_value=note)
    monkeypatch.setattr(brain_graph.brain_store, "update_note", update_mock)

    asyncio.run(brain_graph.mark_stale("a"))

    _, kwargs = update_mock.await_args
    assert kwargs["status"] == "stale"
    assert kwargs["peso_temporal"] == 0.1
    assert kwargs["metadados"]["stale"] is True


def test_garbage_collect_deletes_orphans(monkeypatch):
    class FakeConn:
        def __init__(self):
            self.deleted = None

        async def fetch(self, query):
            return [{"id": "00000000-0000-0000-0000-000000000001"}]

        async def execute(self, query, ids):
            self.deleted = ids

    class FakeAcquire:
        def __init__(self, conn):
            self.conn = conn

        async def __aenter__(self):
            return self.conn

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakePool:
        def __init__(self, conn):
            self.conn = conn

        def acquire(self):
            return FakeAcquire(self.conn)

    conn = FakeConn()
    monkeypatch.setattr(brain_graph, "get_pool", AsyncMock(return_value=FakePool(conn)))

    removed = asyncio.run(brain_graph.garbage_collect())

    assert removed == 1
    assert conn.deleted == ["00000000-0000-0000-0000-000000000001"]
