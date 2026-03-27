from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


_approval_mode: ContextVar[str] = ContextVar("hughie_approval_mode", default="interactive")
_session_id: ContextVar[str | None] = ContextVar("hughie_session_id", default=None)


@dataclass
class ApprovalRequired(Exception):
    action_key: str
    message: str
    approve_label: str = "Autorizar"
    reject_label: str = "Negar"


_decisions: dict[str, dict[str, bool]] = {}


@contextmanager
def approval_context(*, session_id: str, mode: str):
    token_mode = _approval_mode.set(mode)
    token_session = _session_id.set(session_id)
    try:
        yield
    finally:
        _approval_mode.reset(token_mode)
        _session_id.reset(token_session)


def current_session_id() -> str | None:
    return _session_id.get()


def current_approval_mode() -> str:
    return _approval_mode.get()


def register_decision(session_id: str, action_key: str, approved: bool) -> None:
    _decisions.setdefault(session_id, {})[action_key] = approved


def consume_decision(session_id: str, action_key: str) -> bool | None:
    decisions = _decisions.get(session_id)
    if not decisions or action_key not in decisions:
        return None
    approved = decisions.pop(action_key)
    if not decisions:
        _decisions.pop(session_id, None)
    return approved


async def confirm_or_raise(
    *,
    action_key: str,
    prompt: str,
    approve_label: str = "Autorizar",
    reject_label: str = "Negar",
) -> bool:
    session_id = current_session_id()
    mode = current_approval_mode()

    if session_id:
        existing = consume_decision(session_id, action_key)
        if existing is not None:
            return existing

    if mode == "web":
        raise ApprovalRequired(
            action_key=action_key,
            message=prompt,
            approve_label=approve_label,
            reject_label=reject_label,
        )

    loop = asyncio.get_event_loop()
    answer = await loop.run_in_executor(None, lambda: input(f"\n{prompt}\nConfirmar? [s/N]: ").strip().lower())
    return answer in ("s", "sim", "y", "yes")
