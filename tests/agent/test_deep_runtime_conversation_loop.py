from __future__ import annotations

from types import SimpleNamespace

from agent.deep_multi_agent import DeepMABranch, DeepMAResult


def _agent(session_id: str = "parent-session") -> SimpleNamespace:
    return SimpleNamespace(session_id=session_id, _turn_facts={})


class _FinalizerAgent:
    def __init__(self) -> None:
        self.max_iterations = 10
        self.iteration_budget = SimpleNamespace(remaining=9, used=1, max_total=10)
        self.model = "test-model"
        self.provider = "openrouter"
        self.base_url = ""
        self.platform = "cli"
        self.session_id = "parent-session"
        self.context_compressor = SimpleNamespace(last_prompt_tokens=0)
        self.session_input_tokens = 0
        self.session_output_tokens = 0
        self.session_cache_read_tokens = 0
        self.session_cache_write_tokens = 0
        self.session_reasoning_tokens = 0
        self.session_prompt_tokens = 0
        self.session_completion_tokens = 0
        self.session_total_tokens = 0
        self.session_estimated_cost_usd = 0
        self.session_cost_status = "unknown"
        self.session_cost_source = "test"
        self._turn_facts = {
            "route": {"actual": "deep/runtime", "reason": "prefix"},
            "deep": {
                "observed": True,
                "protocol_key": "original_triad_critique",
                "child_session_ids": ["old-a", "old-b", "old-c", "old-d"],
            },
            "coordination": {"observed": True, "agents": 4, "modes": ["deep"]},
            "evidence": {"level": "ok"},
        }
        self._tool_guardrail_halt_decision = None
        self._interrupt_message = None
        self._response_was_previewed = False
        self._current_streamed_assistant_text = ""
        self._current_visible_streamed_assistant_text = ""
        self._skill_nudge_interval = 0
        self._iters_since_skill = 0
        self.valid_tool_names = []
        self._stream_callback = None
        self.persisted_messages = None

    def _save_trajectory(self, *_args, **_kwargs) -> None:
        pass

    def _cleanup_task_resources(self, *_args, **_kwargs) -> None:
        pass

    def _drop_trailing_empty_response_scaffolding(self, _messages) -> None:
        pass

    def _file_mutation_verifier_enabled(self) -> bool:
        return False

    def _turn_completion_explainer_enabled(self) -> bool:
        return False

    def _persist_session(self, messages, _conversation_history) -> None:
        self.persisted_messages = list(messages)

    def _drain_pending_steer(self):
        return None

    def clear_interrupt(self) -> None:
        pass

    def _sync_external_memory_for_turn(self, **_kwargs) -> None:
        pass


def _clean_result() -> DeepMAResult:
    return DeepMAResult(
        protocol_key="original_triad_critique",
        protocol_name="Original Triad Critique",
        clean_native_ma=True,
        subagents=1,
        branches=[
            DeepMABranch(
                role="intent_product_lens",
                label="Intent / Product Lens",
                session_id="child-intent",
                returncode=0,
                output="intent branch output",
                error="",
            )
        ],
        cross_critique_completed=True,
        synthesis_completed=True,
    )


def test_leading_deep_prefix_runs_runtime_children_and_injects_evidence(monkeypatch) -> None:
    from agent import conversation_loop

    calls: list[dict] = []

    def fake_run_deep_multi_agent(**kwargs):
        calls.append(kwargs)
        return _clean_result()

    monkeypatch.setattr(
        "agent.deep_multi_agent.run_deep_multi_agent",
        fake_run_deep_multi_agent,
    )

    prepared = conversation_loop._prepare_deep_runtime_invocation(
        _agent(),
        user_message="deep: 判断这个产品方向是否成立",
        plugin_user_context="existing plugin context",
    )

    assert calls == [
        {
            "user_instruction": "判断这个产品方向是否成立",
            "parent_session_id": "parent-session",
            "source": "prefix",
        }
    ]
    assert prepared.plugin_user_context.startswith("existing plugin context\n\n")
    assert "Deep runtime multi-agent evidence" in prepared.plugin_user_context
    assert "intent branch output" in prepared.plugin_user_context
    assert prepared.terminal_response is None
    assert prepared.failed is False
    assert prepared.turn_facts["deep"]["observed"] is True
    assert prepared.turn_facts["deep"]["child_session_ids"] == ["child-intent"]
    assert prepared.turn_facts["coordination"]["agents"] == 1


def test_embedded_deep_literal_does_not_route_to_runtime(monkeypatch) -> None:
    from agent import conversation_loop

    def fail_if_called(**_kwargs):  # pragma: no cover - assertion guard
        raise AssertionError("embedded deep literal must not start Deep Runtime")

    monkeypatch.setattr("agent.deep_multi_agent.run_deep_multi_agent", fail_if_called)

    prepared = conversation_loop._prepare_deep_runtime_invocation(
        _agent(),
        user_message="please mention the literal deep: token",
        plugin_user_context="existing",
    )

    assert prepared.plugin_user_context == "existing"
    assert prepared.terminal_response is None
    assert prepared.failed is False
    assert prepared.turn_facts == {}


def test_non_deep_turn_clears_stale_deep_facts_before_finalizer(monkeypatch) -> None:
    from agent import conversation_loop
    from agent.turn_finalizer import finalize_turn

    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", lambda *_a, **_kw: [])

    agent = _FinalizerAgent()
    prepared = conversation_loop._prepare_deep_runtime_invocation(
        agent,
        user_message="ordinary later turn after Deep",
        plugin_user_context="existing",
    )
    assert prepared.turn_facts == {}
    assert agent._turn_facts == {}

    result = finalize_turn(
        agent,
        final_response="plain answer",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[
            {"role": "user", "content": "ordinary later turn after Deep"},
            {"role": "assistant", "content": "plain answer"},
        ],
        conversation_history=[],
        effective_task_id="task",
        turn_id="turn-nondeep",
        user_message="ordinary later turn after Deep",
        original_user_message="ordinary later turn after Deep",
        _should_review_memory=False,
        _turn_exit_reason="text_response(finish_reason=stop)",
    )

    final_response = result["final_response"]
    first_line = final_response.splitlines()[0]
    assert first_line.startswith("路径：native｜原因：runtime_default")
    assert "deep/runtime" not in final_response
    assert "Deep ✓" not in final_response
    assert "协同 Agent 4" not in final_response


def test_degraded_deep_workers_fail_loud_without_synthesis_fallback(monkeypatch) -> None:
    from agent import conversation_loop

    degraded = DeepMAResult(
        protocol_key="original_triad_critique",
        protocol_name="Original Triad Critique",
        clean_native_ma=False,
        subagents=1,
        branches=[
            DeepMABranch(
                role="intent_product_lens",
                label="Intent / Product Lens",
                session_id=None,
                returncode=1,
                output="",
                error="provider unavailable",
            )
        ],
        degraded="DEGRADED=partial_workers_failed",
    )
    monkeypatch.setattr(
        "agent.deep_multi_agent.run_deep_multi_agent",
        lambda **_kwargs: degraded,
    )

    prepared = conversation_loop._prepare_deep_runtime_invocation(
        _agent(),
        user_message="deep: 判断这个产品方向是否成立",
        plugin_user_context="",
    )

    assert prepared.plugin_user_context == ""
    assert prepared.failed is True
    assert prepared.terminal_response is not None
    assert "Deep Runtime MA failed" in prepared.terminal_response
    assert "DEGRADED=partial_workers_failed" in prepared.terminal_response
    assert "provider unavailable" in prepared.terminal_response
    assert prepared.turn_facts["deep"]["observed"] is False
    assert prepared.turn_facts["coordination"]["agents"] == 0
