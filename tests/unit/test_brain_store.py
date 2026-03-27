from datetime import datetime, timezone

from hughie.memory import brain_store


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
    return brain_store.BrainNote(**payload)


def test_resolve_conflict_prefers_higher_priority_source():
    existing = _note(fonte="input_manual", confianca=0.3, content="manual")

    resolved = brain_store.resolve_conflict(
        existing,
        {
            "title": "Node A",
            "content": "execucao",
            "note_type": "fact",
            "importance": 1.0,
            "status": "active",
            "source_kind": "runner",
            "metadata": {},
            "fonte": "execucao_real",
            "confianca": 1.0,
            "peso_temporal": 1.0,
            "criado_por": "runner",
            "metadados": {},
        },
    )

    assert resolved["content"] == "execucao"
    assert resolved["fonte"] == "execucao_real"
    assert resolved["confianca"] == 1.0


def test_resolve_conflict_preserves_stronger_existing_source():
    existing = _note(fonte="execucao_real", confianca=1.0, content="verdade forte")

    resolved = brain_store.resolve_conflict(
        existing,
        {
            "title": "Node A",
            "content": "inferencia fraca",
            "note_type": "fact",
            "importance": 0.5,
            "status": "active",
            "source_kind": "worker",
            "metadata": {},
            "fonte": "inferencia",
            "confianca": 0.7,
            "peso_temporal": 0.4,
            "criado_por": "worker",
            "metadados": {},
        },
    )

    assert resolved["content"] == "verdade forte"
    assert resolved["fonte"] == "execucao_real"
    assert resolved["confianca"] == 1.0


def test_note_from_row_backfills_enriched_fields():
    now = datetime.now(timezone.utc)
    note = brain_store._note_from_row(
        {
            "id": "7a9083e1-c75d-46d1-98e4-bc57fb2f9c9b",
            "title": "Teste",
            "content": "Conteudo",
            "type": "fact",
            "importance": 1.0,
            "status": "active",
            "source_kind": "auto_worker",
            "metadata": {"legacy": True},
            "fonte": None,
            "confianca": None,
            "peso_temporal": None,
            "criado_por": None,
            "ultima_atualizacao": now,
            "historico": None,
            "metadados": None,
            "created_at": now,
            "updated_at": now,
        }
    )

    assert note.fonte == "input_manual"
    assert note.confianca == 0.3
    assert note.peso_temporal == 1.0
    assert note.metadados == {"legacy": True}
