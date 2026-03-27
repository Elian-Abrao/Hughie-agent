from __future__ import annotations

import asyncio
import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from langgraph.errors import GraphBubbleUp

_approval_mode: ContextVar[str] = ContextVar("hughie_approval_mode", default="interactive")
_session_id: ContextVar[str | None] = ContextVar("hughie_session_id", default=None)


@dataclass
class ApprovalRequired(GraphBubbleUp):
    action_key: str
    message: str
    approve_label: str = "Autorizar"
    reject_label: str = "Negar"
    scope_key: str | None = None


_decisions: dict[str, dict[str, bool]] = {}
_scope_approvals: dict[str, set[str]] = {}


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


def grant_scope(session_id: str, scope_key: str) -> None:
    _scope_approvals.setdefault(session_id, set()).add(scope_key)


def _path_scope_matches(granted: str, requested: str) -> bool:
    granted_parts = granted.split("|")
    requested_parts = requested.split("|")
    if len(granted_parts) != len(requested_parts):
        return False
    if granted_parts[:-1] != requested_parts[:-1]:
        return False
    try:
        return os.path.commonpath([requested_parts[-1], granted_parts[-1]]) == granted_parts[-1]
    except ValueError:
        return False


def has_scope_approval(session_id: str, scope_key: str | None) -> bool:
    if not scope_key:
        return False
    granted_scopes = _scope_approvals.get(session_id, set())
    if scope_key in granted_scopes:
        return True
    if "_prefix|" not in scope_key:
        return False
    return any(_path_scope_matches(granted, scope_key) for granted in granted_scopes)


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
    scope_key: str | None = None,
) -> bool:
    session_id = current_session_id()
    mode = current_approval_mode()

    if session_id:
        if has_scope_approval(session_id, scope_key):
            return True
        existing = consume_decision(session_id, action_key)
        if existing is not None:
            return existing

    if mode == "web":
        raise ApprovalRequired(
            action_key=action_key,
            message=prompt,
            approve_label=approve_label,
            reject_label=reject_label,
            scope_key=scope_key,
        )

    loop = asyncio.get_event_loop()
    answer = await loop.run_in_executor(None, lambda: input(f"\n{prompt}\nConfirmar? [s/N]: ").strip().lower())
    return answer in ("s", "sim", "y", "yes")
