from __future__ import annotations

from agent.human_status import reduce_human_status_events


def _requested_event(*, kind: str, created_at_ns: int, **extra) -> dict:
    return {
        "mechanism": "human_action",
        "status": "requested",
        "kind": kind,
        "request_id": f"{kind}-old",
        "turn_id": "turn-old",
        "source": "gateway",
        "created_at_ns": created_at_ns,
        **extra,
    }


def test_stale_requested_approval_is_blocked_inspect_not_actionable_wait() -> None:
    snapshot = reduce_human_status_events(
        session_id="stale-approval",
        events=[_requested_event(kind="approval", created_at_ns=1_000_000_000)],
        now=601.0,
        stale_after_seconds=300.0,
    )

    assert snapshot.state == "blocked"
    assert snapshot.state != "needs_approval"
    assert snapshot.human_action_required is True
    assert snapshot.human_action_kind == "inspect"
    assert snapshot.detail == "等待用户批准超时"
    assert snapshot.call_to_action == "请检查是否需要重试"


def test_stale_requested_clarify_is_blocked_inspect_not_actionable_wait() -> None:
    snapshot = reduce_human_status_events(
        session_id="stale-clarify",
        events=[
            _requested_event(
                kind="clarify",
                created_at_ns=1_000_000_000,
                question="请确认是否继续",
            )
        ],
        now=601.0,
        stale_after_seconds=300.0,
    )

    assert snapshot.state == "blocked"
    assert snapshot.state != "needs_input"
    assert snapshot.human_action_required is True
    assert snapshot.human_action_kind == "inspect"
    assert snapshot.detail == "等待用户回复超时"
    assert snapshot.call_to_action == "请检查是否需要重试"
