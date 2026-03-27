import json
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from hughie.memory import episode_store


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


def _episode_row(**overrides):
    payload = {
        "id": "episode-1",
        "session_id": "session-1",
        "created_at": datetime.now(timezone.utc),
        "tarefa": "Atualizar módulo X",
        "resultado": "Módulo X ajustado",
        "tempo_total_segundos": 120,
        "arquivos_modificados": ["/tmp/a.py"],
        "decisoes_tomadas": ["usar SQL"],
        "erros_encontrados": [{"causa": "falha", "solucao": "ajuste"}],
        "aprendizados": ["lembrar do cache"],
        "node_ids_afetados": ["note-1"],
    }
    payload.update(overrides)
    return payload


def test_create_episode_persists_all_fields(monkeypatch):
    class FakeConn:
        async def fetchrow(self, query, *args):
            self.args = args
            return _episode_row()

    conn = FakeConn()
    monkeypatch.setattr(episode_store, "get_pool", AsyncMock(return_value=FakePool(conn)))
    monkeypatch.setattr(episode_store, "embed_document", lambda text: [0.1, 0.2])

    episode = asyncio.run(
        episode_store.create_episode(
            "session-1",
            {
                "tarefa": "Atualizar módulo X",
                "resultado": "Módulo X ajustado",
                "tempo_total_segundos": 120,
                "arquivos_modificados": ["/tmp/a.py"],
                "decisoes_tomadas": ["usar SQL"],
                "erros_encontrados": [{"causa": "falha", "solucao": "ajuste"}],
                "aprendizados": ["lembrar do cache"],
                "node_ids_afetados": ["note-1"],
            },
        )
    )

    assert episode.session_id == "session-1"
    assert episode.tarefa == "Atualizar módulo X"
    assert json.loads(conn.args[4]) == ["/tmp/a.py"]
    assert json.loads(conn.args[7]) == ["lembrar do cache"]


def test_search_similar_episodes_returns_relevant(monkeypatch):
    class FakeConn:
        async def fetch(self, query, *args):
            self.args = args
            return [
                _episode_row(id="episode-1", tarefa="Atualizar módulo X"),
                _episode_row(id="episode-2", tarefa="Refatorar módulo Y"),
            ]

    conn = FakeConn()
    monkeypatch.setattr(episode_store, "get_pool", AsyncMock(return_value=FakePool(conn)))
    monkeypatch.setattr(episode_store, "embed_query", lambda text: [0.2, 0.3])

    episodes = asyncio.run(episode_store.search_similar_episodes("módulo", top_k=2))

    assert [episode.id for episode in episodes] == ["episode-1", "episode-2"]
    assert conn.args[1] == 2


def test_link_episode_creates_graph_relations(monkeypatch):
    monkeypatch.setattr(
        episode_store,
        "get_episode",
        AsyncMock(return_value=episode_store._episode_from_row(_episode_row())),
    )
    monkeypatch.setattr(
        episode_store.brain_store,
        "get_notes_by_ids",
        AsyncMock(return_value=[SimpleNamespace(id="note-1"), SimpleNamespace(id="note-2")]),
    )
    monkeypatch.setattr(
        episode_store.brain_store,
        "create_note",
        AsyncMock(return_value=SimpleNamespace(id="episode-note-1")),
    )
    replace_links = AsyncMock()
    monkeypatch.setattr(episode_store.link_store, "replace_links_for_note", replace_links)

    class FakeConn:
        async def execute(self, query, *args):
            self.args = args

    conn = FakeConn()
    monkeypatch.setattr(episode_store, "get_pool", AsyncMock(return_value=FakePool(conn)))

    episode_note_id = asyncio.run(
        episode_store.link_episode_to_graph("episode-1", ["note-1", "note-2", "note-invalida"])
    )

    assert episode_note_id == "episode-note-1"
    replace_args = replace_links.await_args.args
    assert replace_args[0] == "episode-note-1"
    assert len(replace_args[1]) == 2
    assert conn.args[0] == "episode-1"
