"""Durable mechanism-event ledger for session-scoped status reducers.

The human-status strip needs a backend-owned truth source that is independent
of transcript prose.  This module provides the small append/read surface used
by prompt/approval hooks to record structured lifecycle events.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home

_LOCK = threading.RLock()
_SAFE_SESSION_RE = re.compile(r"[^A-Za-z0-9_.:-]+")


def _safe_session_id(session_id: str) -> str:
    raw = str(session_id or "unknown").strip() or "unknown"
    safe = _SAFE_SESSION_RE.sub("_", raw).strip("._")
    return safe or "unknown"


def _ledger_dir() -> Path:
    return Path(get_hermes_home()) / "mechanism_ledger"


def _ledger_path(session_id: str) -> Path:
    return _ledger_dir() / f"{_safe_session_id(session_id)}.jsonl"


def record_mechanism_event(session_id: str, event: dict[str, Any]) -> dict[str, Any]:
    """Append one mechanism event for *session_id* and return the stored payload."""

    sid = str(session_id or "unknown")
    payload: dict[str, Any] = {"session_id": sid, **dict(event or {})}
    payload.setdefault("created_at_ns", time.time_ns())

    line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    with _LOCK:
        path = _ledger_path(sid)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    return payload


def read_session_mechanisms(session_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    """Read mechanism events for *session_id* in ledger order."""

    path = _ledger_path(session_id)
    if not path.exists():
        return []

    events: list[dict[str, Any]] = []
    with _LOCK:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []

    if limit is not None and limit > 0:
        lines = lines[-limit:]

    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def record_human_action_event(
    *,
    session_id: str,
    status: str,
    kind: str,
    source: str,
    request_id: str | None = None,
    turn_id: str | None = None,
    tool_call_id: str | None = None,
    human_action_kind: str | None = None,
    summary: str | None = None,
    detail: str | None = None,
    call_to_action: str | None = None,
    choice: str | None = None,
    reason: str | None = None,
    choices: list[str] | None = None,
    surface: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Append a normalized ``human_action`` lifecycle event."""

    event: dict[str, Any] = {
        "mechanism": "human_action",
        "status": str(status or ""),
        "kind": str(kind or ""),
        "source": str(source or ""),
    }
    optional = {
        "request_id": request_id,
        "turn_id": turn_id,
        "tool_call_id": tool_call_id,
        "human_action_kind": human_action_kind,
        "summary": summary,
        "detail": detail,
        "call_to_action": call_to_action,
        "choice": choice,
        "reason": reason,
        "choices": list(choices) if choices else None,
        "surface": surface,
    }
    for key, value in optional.items():
        if value is not None and value != "":
            event[key] = value
    for key, value in extra.items():
        if value is not None and value != "":
            event[key] = value
    return record_mechanism_event(session_id, event)
