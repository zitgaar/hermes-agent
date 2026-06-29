from __future__ import annotations

from agent.turn_finalizer import finalize_turn


class _StubBudget:
    used = 1
    max_total = 10
    remaining = 9


class _StubCompressor:
    last_prompt_tokens = 0


class _StubAgent:
    def __init__(self):
        self.max_iterations = 10
        self.iteration_budget = _StubBudget()
        self.context_compressor = _StubCompressor()
        self.model = "stub/model"
        self.provider = "stub"
        self.base_url = "http://stub"
        self.session_id = "session-123"
        self.quiet_mode = True
        self.platform = "cli"
        self._interrupt_requested = False
        self._interrupt_message = None
        self._tool_guardrail_halt_decision = None
        self._response_was_previewed = False
        self._skill_nudge_interval = 0
        self._iters_since_skill = 0
        for attr in (
            "session_input_tokens",
            "session_output_tokens",
            "session_cache_read_tokens",
            "session_cache_write_tokens",
            "session_reasoning_tokens",
            "session_prompt_tokens",
            "session_completion_tokens",
            "session_total_tokens",
            "session_estimated_cost_usd",
        ):
            setattr(self, attr, 0)
        self.session_cost_status = "ok"
        self.session_cost_source = "stub"
        self.clear_count = 0

    def _save_trajectory(self, *args, **kwargs):
        pass

    def _cleanup_task_resources(self, *args, **kwargs):
        pass

    def _drop_trailing_empty_response_scaffolding(self, *args, **kwargs):
        pass

    def _persist_session(self, *args, **kwargs):
        pass

    def _emit_status(self, *args, **kwargs):
        pass

    def _safe_print(self, *args, **kwargs):
        pass

    def _file_mutation_verifier_enabled(self):
        return False

    def _turn_completion_explainer_enabled(self):
        return False

    def _drain_pending_steer(self):
        return None

    def clear_interrupt(self):
        self.clear_count += 1

    def _sync_external_memory_for_turn(self, **kwargs):
        pass


def _finalize(agent):
    return finalize_turn(
        agent,
        final_response="final answer",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "final answer"},
        ],
        conversation_history=None,
        effective_task_id="task-123",
        turn_id="turn-123",
        user_message="hello",
        original_user_message="hello",
        _should_review_memory=False,
        _turn_exit_reason="text_response(finish_reason=stop)",
    )


def test_finalize_turn_calls_watchtower_hook_once_with_result_context(monkeypatch):
    calls = []

    def fake_emit(**kwargs):
        calls.append(kwargs)
        return True

    monkeypatch.setattr("agent.session_watchtower.emit_turn_finalized_event", fake_emit)
    agent = _StubAgent()

    result = _finalize(agent)

    assert result["final_response"] == "final answer"
    assert len(calls) == 1
    call = calls[0]
    assert call["result"] is result
    assert call["task_id"] == "task-123"
    assert call["turn_id"] == "turn-123"
    assert call["agent"] is agent


def test_finalize_turn_watchtower_hook_exception_fails_open(monkeypatch):
    def raising_emit(**kwargs):
        raise RuntimeError("watchtower unavailable")

    monkeypatch.setattr("agent.session_watchtower.emit_turn_finalized_event", raising_emit)
    agent = _StubAgent()

    result = _finalize(agent)

    assert result["final_response"] == "final answer"
    assert result["completed"] is True
    assert agent.clear_count == 1
