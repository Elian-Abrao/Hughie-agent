import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from langchain_core.messages import HumanMessage

from hughie.core import nodes


async def _drain_progress(events: list[tuple[str, str]], stage: str, message: str) -> None:
    events.append((stage, message))


def test_retrieve_context_uses_partial_context_when_rag_times_out(monkeypatch):
    progress_events: list[tuple[str, str]] = []

    monkeypatch.setattr(
        nodes,
        "get_settings",
        lambda: SimpleNamespace(
            context_rag_top_k=6,
            context_history_limit=12,
            context_timeout_seconds=0.01,
        ),
    )
    monkeypatch.setattr(
        nodes.conversation_store,
        "get_recent",
        AsyncMock(return_value=[SimpleNamespace(role="user", content="oi")]),
    )

    async def slow_rag(*args, **kwargs):
        await asyncio.sleep(0.05)
        return {"context": "nao deveria chegar", "results": [1], "episodes": [1]}

    monkeypatch.setattr(nodes, "retrieve_context_v2", slow_rag)

    state = {
        "messages": [HumanMessage(content="me ajuda")],
        "history": [],
        "session_id": "sessao-1",
        "brain_context": "",
        "progress_callback": lambda stage, message: _drain_progress(progress_events, stage, message),
    }

    result = asyncio.run(nodes.retrieve_context(state))

    assert result["brain_context"] == ""
    assert len(result["history"]) == 1
    assert any(stage == "context:partial" for stage, _ in progress_events)


def test_retrieve_context_uses_configured_limits(monkeypatch):
    monkeypatch.setattr(
        nodes,
        "get_settings",
        lambda: SimpleNamespace(
            context_rag_top_k=4,
            context_history_limit=7,
            context_timeout_seconds=1.0,
        ),
    )
    history_mock = AsyncMock(return_value=[])
    rag_mock = AsyncMock(return_value={"context": "", "results": [], "episodes": []})
    monkeypatch.setattr(nodes.conversation_store, "get_recent", history_mock)
    monkeypatch.setattr(nodes, "retrieve_context_v2", rag_mock)

    state = {
        "messages": [HumanMessage(content="resuma isso")],
        "history": [],
        "session_id": "sessao-2",
        "brain_context": "",
    }

    asyncio.run(nodes.retrieve_context(state))

    history_mock.assert_awaited_once_with("sessao-2", limit=7)
    _, kwargs = rag_mock.await_args
    assert kwargs["top_k"] == 4
