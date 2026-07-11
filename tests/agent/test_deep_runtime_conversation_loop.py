from __future__ import annotations

from types import SimpleNamespace

from agent.deep_multi_agent import DeepMABranch, DeepMAResult


def _agent(session_id: str = "parent-session") -> SimpleNamespace:
    return SimpleNamespace(session_id=session_id, _turn_facts={})


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
