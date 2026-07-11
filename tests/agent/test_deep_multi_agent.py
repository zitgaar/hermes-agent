import sys
from types import SimpleNamespace


ORIGINAL_TRIAD_ROLES = [
    "intent_product_lens",
    "architecture_product_lens",
    "construction_execution_lens",
    "risk_claim_lens",
]
ORIGINAL_TRIAD_CHILD_SESSION_IDS = [
    "child-intent-product-lens",
    "child-architecture-product-lens",
    "child-construction-execution-lens",
    "child-risk-claim-lens",
]


def test_run_deep_multi_agent_records_protocol_aware_worker_evidence(monkeypatch) -> None:
    from agent import deep_multi_agent

    commands = []
    recorded = []

    def fake_run(command, **kwargs):
        commands.append(list(command))
        source = command[command.index("--source") + 1]
        source_slug = source.replace("deep-ma-original-triad-", "")
        return SimpleNamespace(
            returncode=0,
            stdout=f"fake branch output from {source}",
            stderr=f"session_id: child-{source_slug}\n",
        )

    monkeypatch.setattr(deep_multi_agent.subprocess, "run", fake_run)
    monkeypatch.setattr(deep_multi_agent, "_link_child_sessions_to_parent", lambda **_kwargs: 4)
    monkeypatch.setattr(
        "agent.mechanism_ledger.record_mechanism_event",
        lambda session_id, event: recorded.append({"session_id": session_id, **event}),
    )

    result = deep_multi_agent.run_deep_multi_agent(
        user_instruction="判断这个产品方向是否成立",
        parent_session_id="parent-session",
        source="prefix",
        timeout_seconds=5,
    )

    assert result.clean_native_ma is True
    assert result.protocol_key == "original_triad_critique"
    assert result.protocol_name == "Original Triad Critique"
    assert result.subagents == 4
    assert [branch.role for branch in result.branches] == ORIGINAL_TRIAD_ROLES
    assert [branch.session_id for branch in result.branches] == ORIGINAL_TRIAD_CHILD_SESSION_IDS
    assert len(commands) == 4
    assert all(command[:5] == [sys.executable, "-m", "hermes_cli.main", "chat", "--cli"] for command in commands)
    assert all("--toolsets" in command and "none" in command for command in commands)

    construction_command = commands[ORIGINAL_TRIAD_ROLES.index("construction_execution_lens")]
    insert_at = construction_command.index("--ignore-rules")
    assert construction_command[insert_at - 4 : insert_at] == [
        "--provider",
        "opencode-go",
        "--model",
        "glm-5.2",
    ]

    assert recorded
    event = recorded[-1]
    assert event["session_id"] == "parent-session"
    assert event["mechanism"] == "deep"
    assert event["status"] == "workers.completed"
    payload = event["payload"]
    assert payload["kind"] == "multi_agent"
    assert payload["phase"] == "workers"
    assert payload["protocol"] == "Original Triad Critique"
    assert payload["protocol_key"] == "original_triad_critique"
    assert payload["wrong_object_replaced"] is True
    assert payload["roles"] == ORIGINAL_TRIAD_ROLES
    assert payload["child_session_ids"] == ORIGINAL_TRIAD_CHILD_SESSION_IDS
    assert payload["clean_native_ma"] is True
    assert payload["linked_child_sessions"] == 4
    assert payload["role_model_overrides"] == {
        "construction_execution_lens": {"provider": "opencode-go", "model": "glm-5.2"}
    }


def test_build_deep_ma_synthesis_prompt_uses_runtime_evidence_not_textual_scaffold() -> None:
    from agent.deep_multi_agent import DeepMABranch, DeepMAResult, build_deep_ma_synthesis_prompt

    result = DeepMAResult(
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
                output="intent output",
                error="",
            )
        ],
        cross_critique_completed=True,
        synthesis_completed=True,
    )

    prompt = build_deep_ma_synthesis_prompt("原问题", result, skill_prompt="")

    assert "Deep runtime multi-agent evidence" in prompt
    assert "Intent / Product Lens 子 agent" in prompt
    assert "intent output" in prompt
    assert "[IMPORTANT: The user has invoked" not in prompt
    assert "subagents=1" in prompt


def test_deep_result_turn_facts_require_clean_runtime_for_observed_success() -> None:
    from agent.deep_multi_agent import DeepMABranch, DeepMAResult, deep_turn_facts

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
                error="failed",
            )
        ],
        degraded="DEGRADED=partial_workers_failed",
    )

    facts = deep_turn_facts(degraded, route_actual="deep/runtime-degraded")

    assert facts["route"] == {"actual": "deep/runtime-degraded", "reason": "user_requested_deep"}
    assert facts["deep"]["observed"] is False
    assert facts["deep"]["protocol_key"] is None
    assert facts["coordination"]["agents"] == 0
