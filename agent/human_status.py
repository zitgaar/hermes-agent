"""Reduce mechanism-ledger events into a human-facing status snapshot."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class HumanStatusSnapshot:
    session_id: str
    state: str
    summary: str
    detail: str = ""
    call_to_action: str = ""
    human_action_required: bool = False
    human_action_kind: str = "none"
    source: str = "mechanism_ledger"
    updated_at_ns: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_APPROVAL_CHOICES = {"once", "session", "always", "approve", "approved", "allow"}
_DENY_CHOICES = {"deny", "denied", "timeout", "cancel", "cancelled", "canceled"}
_ACTION_PRIORITY = {"approval": 0, "approve": 0, "clarify": 10}


def _event_time(event: dict[str, Any]) -> int:
    try:
        return int(event.get("created_at_ns") or 0)
    except (TypeError, ValueError):
        return 0


def _is_stale_requested_event(
    event: dict[str, Any],
    *,
    now: float,
    stale_after_seconds: float,
) -> bool:
    created_at_ns = _event_time(event)
    if created_at_ns <= 0:
        return False
    try:
        now_seconds = float(now)
        stale_after = float(stale_after_seconds)
    except (TypeError, ValueError):
        return False
    if stale_after < 0:
        return False
    return now_seconds - (created_at_ns / 1_000_000_000) > stale_after


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _request_key(event: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        _text(event.get("request_id")),
        _text(event.get("turn_id")),
        _text(event.get("kind")),
        _text(event.get("source")),
    )


def _infer_action_kind(event: dict[str, Any]) -> str:
    explicit = _text(event.get("human_action_kind"))
    if explicit:
        return explicit
    kind = _text(event.get("kind"))
    if kind in {"approval", "approve"}:
        return "approve"
    if event.get("choices"):
        return "choose"
    return "reply"


def _requested_snapshot(session_id: str, event: dict[str, Any]) -> HumanStatusSnapshot:
    kind = _text(event.get("kind"))
    action_kind = _infer_action_kind(event)
    is_approval = kind in {"approval", "approve"} or action_kind == "approve"
    if is_approval:
        state = "needs_approval"
        default_summary = "需要你确认"
        default_detail = "等待批准执行命令"
        default_cta = "请批准或拒绝"
    elif action_kind == "choose":
        state = "needs_input"
        default_summary = "需要你选择"
        default_detail = _text(event.get("question")) or _text(event.get("detail"))
        default_cta = "请选择一个选项"
    else:
        state = "needs_input"
        default_summary = "需要你回复"
        default_detail = _text(event.get("question")) or _text(event.get("detail"))
        default_cta = "请回复以继续"
    return HumanStatusSnapshot(
        session_id=session_id,
        state=state,
        summary=_text(event.get("summary")) or default_summary,
        detail=_text(event.get("detail")) or default_detail,
        call_to_action=_text(event.get("call_to_action")) or default_cta,
        human_action_required=True,
        human_action_kind=action_kind,
        source=_text(event.get("source")) or "mechanism_ledger",
        updated_at_ns=_event_time(event) or None,
    )


def _blocked_snapshot(session_id: str, event: dict[str, Any]) -> HumanStatusSnapshot:
    status = _text(event.get("status")).casefold()
    choice = _text(event.get("choice")).casefold()
    detail = _text(event.get("detail"))
    if not detail:
        if status == "timeout" or choice == "timeout":
            detail = "等待用户回复超时" if _text(event.get("kind")) == "clarify" else "等待用户批准超时"
        elif choice in {"deny", "denied"}:
            detail = "用户已拒绝执行命令"
        elif status in {"cancelled", "canceled", "cancel"}:
            detail = "等待用户操作已取消"
        else:
            detail = "需要检查当前状态"
    return HumanStatusSnapshot(
        session_id=session_id,
        state="blocked",
        summary="已阻塞 · 需要处理",
        detail=detail,
        call_to_action="请检查是否需要重试",
        human_action_required=True,
        human_action_kind="inspect",
        source=_text(event.get("source")) or "mechanism_ledger",
        updated_at_ns=_event_time(event) or None,
    )


def _completed_snapshot(session_id: str, event: dict[str, Any] | None = None) -> HumanStatusSnapshot:
    return HumanStatusSnapshot(
        session_id=session_id,
        state="completed",
        summary="已完成 · 不需要你操作",
        human_action_required=False,
        human_action_kind="none",
        source=_text((event or {}).get("source")) or "mechanism_ledger",
        updated_at_ns=_event_time(event or {}) or None,
    )


def _idle_snapshot(session_id: str) -> HumanStatusSnapshot:
    return HumanStatusSnapshot(
        session_id=session_id,
        state="idle",
        summary="空闲 · 不需要你操作",
        human_action_required=False,
        human_action_kind="none",
    )


def reduce_human_status_events(
    *,
    session_id: str,
    events: list[dict[str, Any]],
    now: float,
    stale_after_seconds: float = 300.0,
) -> HumanStatusSnapshot:
    """Reduce recent mechanism events into the current human-facing status."""

    pending: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    latest_terminal: dict[str, Any] | None = None
    latest_any: dict[str, Any] | None = None

    for event in sorted((e for e in events if isinstance(e, dict)), key=_event_time):
        if event.get("mechanism") != "human_action":
            continue
        latest_any = event
        key = _request_key(event)
        status = _text(event.get("status")).casefold()
        if status == "requested":
            if _is_stale_requested_event(
                event,
                now=now,
                stale_after_seconds=stale_after_seconds,
            ):
                latest_terminal = {**event, "status": "timeout"}
                pending.pop(key, None)
                continue
            pending[key] = event
            continue
        if status in {"resolved", "timeout", "cancelled", "canceled", "cancel"}:
            pending.pop(key, None)
            latest_terminal = event

    if pending:
        selected = sorted(
            pending.values(),
            key=lambda event: (
                _ACTION_PRIORITY.get(_text(event.get("kind")), 50),
                -_event_time(event),
            ),
        )[0]
        return _requested_snapshot(session_id, selected)

    if latest_terminal is not None:
        status = _text(latest_terminal.get("status")).casefold()
        choice = _text(latest_terminal.get("choice")).casefold()
        if status in {"timeout", "cancelled", "canceled", "cancel"} or choice in _DENY_CHOICES:
            return _blocked_snapshot(session_id, latest_terminal)
        if status == "resolved" and (not choice or choice in _APPROVAL_CHOICES or choice):
            return _completed_snapshot(session_id, latest_terminal)

    if latest_any is not None:
        return _completed_snapshot(session_id, latest_any)
    return _idle_snapshot(session_id)


def runtime_from_mechanism_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """Return a reducer-friendly runtime dict for a single mechanism event."""

    if not isinstance(event, dict):
        return None
    if event.get("mechanism") == "human_action":
        return dict(event)
    if event.get("mechanism") == "turn_receipt":
        receipt = event.get("receipt") if isinstance(event.get("receipt"), dict) else {}
        return {**event, **receipt}
    return None


def reduce_human_status(
    *,
    session_id: str,
    runtime: dict[str, Any] | None,
    now: float,
    stale_after_seconds: float = 300.0,
) -> HumanStatusSnapshot:
    """Compatibility wrapper for reducing a single runtime/mechanism event."""

    if not runtime:
        return _idle_snapshot(session_id)
    if runtime.get("mechanism") == "human_action":
        return reduce_human_status_events(
            session_id=session_id,
            events=[runtime],
            now=now,
            stale_after_seconds=stale_after_seconds,
        )
    status = _text(runtime.get("status")).casefold()
    if status in {"failed", "error"}:
        return HumanStatusSnapshot(
            session_id=session_id,
            state="failed",
            summary="运行失败",
            detail=_text(runtime.get("detail")) or _text(runtime.get("error")),
            call_to_action="请检查或重试",
            human_action_required=True,
            human_action_kind="retry",
            source="turn_receipt",
        )
    if status in {"interrupted", "cancelled", "canceled"}:
        return HumanStatusSnapshot(
            session_id=session_id,
            state="blocked",
            summary="已阻塞 · 需要处理",
            detail="运行已被中断",
            call_to_action="请检查是否需要重试",
            human_action_required=True,
            human_action_kind="inspect",
            source="turn_receipt",
        )
    if status in {"running", "started"}:
        return HumanStatusSnapshot(
            session_id=session_id,
            state="running",
            summary="正在运行 · 不需要你操作",
            human_action_required=False,
            human_action_kind="none",
            source="turn_receipt",
        )
    if status == "completed" or runtime.get("completed") is True:
        return _completed_snapshot(session_id, runtime)
    return _idle_snapshot(session_id)
