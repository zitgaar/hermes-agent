"""Human-status lifecycle coverage for gateway clarify prompts."""

from __future__ import annotations


def _clear_clarify_state() -> None:
    from tools import clarify_gateway as cm

    with cm._lock:
        cm._entries.clear()
        cm._session_index.clear()


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


class TestClarifyHumanStatusLifecycle:
    def setup_method(self) -> None:
        _clear_clarify_state()

    def test_free_text_clarify_records_requested_and_resolved_lifecycle(self) -> None:
        from tools import clarify_gateway as cm

        cm.register(
            "clarify-free",
            "session-free",
            "请说明要保留哪个版本",
            None,
        )

        waiting = _snapshot("session-free")
        assert waiting.state == "needs_input"
        assert waiting.human_action_required is True
        assert waiting.human_action_kind == "reply"
        assert waiting.summary == "需要你回复"
        assert waiting.detail == "请说明要保留哪个版本"
        assert waiting.call_to_action == "请回复以继续"

        assert cm.resolve_gateway_clarify("clarify-free", "保留新版") is True
        assert cm.wait_for_response("clarify-free", timeout=0.1) == "保留新版"

        events = _session_events("session-free")
        assert [event["status"] for event in events] == ["requested", "resolved"]
        assert events[-1]["choice"] == "保留新版"

        resolved = _snapshot("session-free")
        assert resolved.human_action_required is False
        assert resolved.state == "completed"

    def test_choice_clarify_records_choose_copy(self) -> None:
        from tools import clarify_gateway as cm

        cm.register(
            "clarify-choice",
            "session-choice",
            "请选择部署目标",
            ["staging", "prod"],
        )

        waiting = _snapshot("session-choice")
        assert waiting.state == "needs_input"
        assert waiting.human_action_kind == "choose"
        assert waiting.summary == "需要你选择"
        assert waiting.detail == "请选择部署目标"
        assert waiting.call_to_action == "请选择一个选项"

    def test_timeout_records_blocked_inspect_lifecycle(self) -> None:
        from tools import clarify_gateway as cm

        cm.register(
            "clarify-timeout",
            "session-timeout",
            "请确认是否继续执行发布",
            None,
        )

        assert cm.wait_for_response("clarify-timeout", timeout=0.01) is None

        events = _session_events("session-timeout")
        assert [event["status"] for event in events] == ["requested", "timeout"]

        timed_out = _snapshot("session-timeout")
        assert timed_out.state == "blocked"
        assert timed_out.human_action_required is True
        assert timed_out.human_action_kind == "inspect"
        assert timed_out.summary == "已阻塞 · 需要处理"
        assert timed_out.detail == "等待用户回复超时"
        assert timed_out.call_to_action == "请检查是否需要重试"
