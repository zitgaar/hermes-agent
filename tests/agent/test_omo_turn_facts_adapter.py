from __future__ import annotations

import json
from typing import Any

from agent.omo_turn_facts_adapter import extract_omo_turn_facts_from_messages


def _assistant_call(tool_name: str, call_id: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "tool_calls": [
            {"id": call_id, "function": {"name": tool_name, "arguments": "{}"}},
        ],
    }


def _tool_message(content: str, *, call_id: str = "omo-call", name: str | None = None) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": "tool", "tool_call_id": call_id, "content": content}
    if name is not None:
        msg["name"] = name
    return msg


def _payload() -> dict[str, Any]:
    return {
        "turn_facts_schema": "hermes.omo_turn_facts.v1",
        "turn_facts": {
            "route": {"actual": "opencode/omo", "reason": "user_requested_omo"},
            "opencode": {"observed": True, "source": "hermes-omo-executor"},
            "tools": {"called": True, "names": ["omo_executor"], "total": 1, "succeeded": 1, "failed": 0},
            "delegation": {"observed": True, "agents": 2, "subagents": 5},
            "omo": {
                "parent_session_id": "ses_parent",
                "descendant_session_ids": ["ses_1", "ses_2", "ses_3", "ses_4", "ses_5"],
                "session_created_events": 9,
            },
            "evidence": {"level": "ok", "sources": ["/tmp/omo/evidence-report.md"]},
        },
    }


def _expected_facts() -> dict[str, Any]:
    facts = dict(_payload()["turn_facts"])
    facts["coordination"] = {
        "observed": True,
        "agents": 6,
        "modes": ["omo"],
        "breakdown": {
            "omo_parent": 1,
            "omo_descendants": 5,
            "session_created_events": 9,
        },
    }
    return facts


def test_extracts_schema_marked_json_from_trusted_runtime_tool_call() -> None:
    messages: list[dict[str, Any]] = [
        _assistant_call("omo_executor", "omo-call"),
        _tool_message(json.dumps(_payload(), ensure_ascii=False), call_id="omo-call"),
    ]

    facts = extract_omo_turn_facts_from_messages(messages)

    assert facts == [_expected_facts()]


def test_extracts_schema_marked_json_nested_in_trusted_runtime_output() -> None:
    content = json.dumps({"output": json.dumps(_payload(), ensure_ascii=False), "exit_code": 0}, ensure_ascii=False)
    messages: list[dict[str, Any]] = [
        _assistant_call("omo_executor", "omo-call"),
        _tool_message(content, call_id="omo-call"),
    ]

    facts = extract_omo_turn_facts_from_messages(messages)

    assert facts == [_expected_facts()]


def test_rejects_schema_echo_from_untrusted_terminal_tool() -> None:
    messages: list[dict[str, Any]] = [
        _assistant_call("terminal", "terminal-call"),
        _tool_message(json.dumps(_payload(), ensure_ascii=False), call_id="terminal-call", name="terminal"),
    ]

    assert extract_omo_turn_facts_from_messages(messages) == []


def test_rejects_trusted_payload_without_matching_assistant_call_id() -> None:
    messages: list[dict[str, Any]] = [
        _tool_message(json.dumps(_payload(), ensure_ascii=False), call_id="omo-call", name="omo_executor"),
    ]

    assert extract_omo_turn_facts_from_messages(messages) == []


def test_rejects_assistant_prose_even_when_it_mentions_schema() -> None:
    messages: list[dict[str, Any]] = [
        {"role": "assistant", "content": json.dumps(_payload(), ensure_ascii=False)},
    ]

    assert extract_omo_turn_facts_from_messages(messages) == []


def test_computes_coordination_from_verified_omo_sessions_not_raw_events() -> None:
    messages: list[dict[str, Any]] = [
        _assistant_call("omo_executor", "omo-call"),
        _tool_message(json.dumps(_payload(), ensure_ascii=False), call_id="omo-call"),
    ]

    facts = extract_omo_turn_facts_from_messages(messages)[0]

    assert facts["coordination"] == {
        "observed": True,
        "agents": 6,
        "modes": ["omo"],
        "breakdown": {
            "omo_parent": 1,
            "omo_descendants": 5,
            "session_created_events": 9,
        },
    }
