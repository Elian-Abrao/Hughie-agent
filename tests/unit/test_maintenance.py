import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from hughie.memory import maintenance


def _note(**overrides):
    now = datetime.now(timezone.utc)
    payload = {
        "id": "note-1",
        "title": "Node A",
        "content": "conteudo atual",
        "type": "fact",
        "importance": 1.0,
        "status": "active",
        "source_kind": "auto_worker",
        "metadata": {"legacy": True},
        "fonte": "input_manual",
        "confianca": 0.3,
        "peso_temporal": 0.9,
        "criado_por": "worker",
        "ultima_atualizacao": now,
        "historico": [],
        "metadados": {"novo": True},
        "created_at": now,
        "updated_at": now,
    }
    payload.update(overrides)
    return type("FakeNote", (), payload)()


def test_run_decay_delegates_to_brain_store(monkeypatch):
    decay_mock = AsyncMock(return_value=4)
    monkeypatch.setattr(maintenance.brain_store, "decay_temporal_weight", decay_mock)

    updated = asyncio.run(maintenance.run_decay())

    assert updated == 4
    decay_mock.assert_awaited_once_with(days_without_access=7, decay_factor=0.1)


def test_run_garbage_collection_delegates_to_graph(monkeypatch):
    gc_mock = AsyncMock(return_value=2)
    monkeypatch.setattr(maintenance.brain_graph, "garbage_collect", gc_mock)

    removed = asyncio.run(maintenance.run_garbage_collection())

    assert removed == 2
    gc_mock.assert_awaited_once()


def test_run_conflict_resolution_promotes_stronger_history(monkeypatch):
    note = _note(
        fonte="input_manual",
        historico=[
            {
                "title": "Node A",
                "content": "conteudo validado",
                "type": "fact",
                "importance": 1.0,
                "status": "active",
                "source_kind": "executor",
                "metadata": {"legacy": True},
                "fonte": "execucao_real",
                "confianca": 1.0,
                "peso_temporal": 1.0,
                "criado_por": "executor",
                "metadados": {"novo": True},
            }
        ],
    )
    monkeypatch.setattr(maintenance.brain_store, "list_notes", AsyncMock(return_value=[note]))
    update_mock = AsyncMock(return_value=note)
    monkeypatch.setattr(maintenance.brain_store, "update_note", update_mock)

    resolved = asyncio.run(maintenance.run_conflict_resolution(limit=10))

    assert resolved == 1
    _, kwargs = update_mock.await_args
    assert kwargs["fonte"] == "execucao_real"
    assert kwargs["confianca"] == 1.0


def test_run_all_returns_all_counters(monkeypatch):
    monkeypatch.setattr(maintenance, "run_decay", AsyncMock(return_value=3))
    monkeypatch.setattr(maintenance, "run_garbage_collection", AsyncMock(return_value=1))
    monkeypatch.setattr(maintenance, "run_conflict_resolution", AsyncMock(return_value=2))

    result = asyncio.run(maintenance.run_all())

    assert result == {"decayed": 3, "garbage_collected": 1, "conflicts_resolved": 2}
