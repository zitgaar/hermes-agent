"""Human-status lifecycle coverage for dangerous-command approvals."""

from __future__ import annotations

import threading

import tools.approval as approval_module


def _session_events(session_key: str) -> list[dict]:
    from agent.mechanism_ledger import read_session_mechanisms

    return read_session_mechanisms(session_key)


def _snapshot(session_key: str):
    from agent.human_status import reduce_human_status_events

    return reduce_human_status_events(
        session_id=session_key,
        events=_session_events(session_key),
        now=101.0,
    )


def _approval_payload(command: str = "rm -rf /tmp/human-status-target") -> dict:
    return {
        "command": command,
        "pattern_key": "rm_rf_tmp",
        "pattern_keys": ["rm_rf_tmp"],
        "description": "recursive delete",
        "allow_permanent": True,
    }


class TestApprovalHumanStatusLifecycle:
    def setup_method(self) -> None:
        approval_module.clear_session("approval-human-status")

    def teardown_method(self) -> None:
        approval_module.clear_session("approval-human-status")

    def test_gateway_approval_records_requested_and_approved_lifecycle(self, monkeypatch) -> None:
        session_key = "approval-human-status"
        notified = threading.Event()
        finished = {}

        monkeypatch.setattr(approval_module, "_get_approval_config", lambda: {"gateway_timeout": 5})
        monkeypatch.setattr(approval_module, "is_interrupted", lambda: False)

        def notify(_approval_data: dict) -> None:
            notified.set()

        def run_wait() -> None:
            finished["decision"] = approval_module._await_gateway_decision(
                session_key,
                notify,
                _approval_payload(),
                surface="tui",
            )

        thread = threading.Thread(target=run_wait)
        thread.start()
        assert notified.wait(timeout=1)

        waiting = _snapshot(session_key)
        assert waiting.state == "needs_approval"
        assert waiting.human_action_required is True
        assert waiting.human_action_kind == "approve"
        assert waiting.summary == "需要你确认"
        assert waiting.detail == "等待批准执行命令"
        assert waiting.call_to_action == "请批准或拒绝"

        assert approval_module.resolve_gateway_approval(session_key, "once") == 1
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert finished["decision"] == {"resolved": True, "choice": "once", "reason": None}

        events = _session_events(session_key)
        assert [event["status"] for event in events] == ["requested", "resolved"]
        assert events[-1]["choice"] == "once"

        resolved = _snapshot(session_key)
        assert resolved.human_action_required is False
        assert resolved.state == "completed"

    def test_gateway_approval_deny_records_blocked_inspect_lifecycle(self, monkeypatch) -> None:
        session_key = "approval-human-status"
        notified = threading.Event()
        finished = {}

        monkeypatch.setattr(approval_module, "_get_approval_config", lambda: {"gateway_timeout": 5})
        monkeypatch.setattr(approval_module, "is_interrupted", lambda: False)

        thread = threading.Thread(
            target=lambda: finished.__setitem__(
                "decision",
                approval_module._await_gateway_decision(
                    session_key,
                    lambda _approval_data: notified.set(),
                    _approval_payload("rm -rf /tmp/denied-human-status-target"),
                    surface="gateway",
                ),
            )
        )
        thread.start()
        assert notified.wait(timeout=1)

        assert approval_module.resolve_gateway_approval(session_key, "deny", reason="太危险") == 1
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert finished["decision"] == {"resolved": True, "choice": "deny", "reason": "太危险"}

        events = _session_events(session_key)
        assert [event["status"] for event in events] == ["requested", "resolved"]
        assert events[-1]["choice"] == "deny"
        assert events[-1]["reason"] == "太危险"

        denied = _snapshot(session_key)
        assert denied.state == "blocked"
        assert denied.human_action_required is True
        assert denied.human_action_kind == "inspect"
        assert denied.detail == "用户已拒绝执行命令"
        assert denied.call_to_action == "请检查是否需要重试"

    def test_gateway_approval_timeout_records_blocked_inspect_lifecycle(self, monkeypatch) -> None:
        session_key = "approval-human-status"
        notified = threading.Event()

        monkeypatch.setattr(approval_module, "_get_approval_config", lambda: {"gateway_timeout": 0.01})
        monkeypatch.setattr(approval_module, "is_interrupted", lambda: False)

        decision = approval_module._await_gateway_decision(
            session_key,
            lambda _approval_data: notified.set(),
            _approval_payload("rm -rf /tmp/timeout-human-status-target"),
            surface="gateway",
        )

        assert notified.is_set()
        assert decision == {"resolved": False, "choice": None, "reason": None}

        events = _session_events(session_key)
        assert [event["status"] for event in events] == ["requested", "timeout"]

        timed_out = _snapshot(session_key)
        assert timed_out.state == "blocked"
        assert timed_out.human_action_required is True
        assert timed_out.human_action_kind == "inspect"
        assert timed_out.detail == "等待用户批准超时"
        assert timed_out.call_to_action == "请检查是否需要重试"
