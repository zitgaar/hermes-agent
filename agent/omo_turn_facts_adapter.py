from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

SCHEMA = "hermes.omo_turn_facts.v1"
_TRUSTED_OMO_TOOL_NAMES = frozenset({"omo_executor", "oh_my_openagent", "omo"})


def extract_omo_turn_facts_from_messages(messages: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Extract OMO turn facts only from trusted runtime-owned tool results.

    A schema-looking JSON blob in arbitrary tool stdout or assistant prose is
    not evidence.  The payload is accepted only when a prior assistant tool call
    used a trusted OMO producer name and the subsequent tool message carries the
    matching tool_call_id.  Tool messages with an explicit non-OMO name are
    rejected even when the call id matches, preserving the call-id boundary.
    """

    trusted_call_ids = _trusted_omo_call_ids(messages or [])
    if not trusted_call_ids:
        return []

    facts: list[dict[str, Any]] = []
    for message in messages or []:
        if not isinstance(message, Mapping) or message.get("role") != "tool":
            continue
        call_id = str(message.get("tool_call_id") or message.get("call_id") or "").strip()
        if not call_id or call_id not in trusted_call_ids:
            continue
        explicit_name = str(message.get("name") or message.get("tool_name") or "").strip()
        if explicit_name and explicit_name not in _TRUSTED_OMO_TOOL_NAMES:
            continue
        facts.extend(_extract_from_text(str(message.get("content") or "")))
    return facts


def _trusted_omo_call_ids(messages: list[dict[str, Any]]) -> set[str]:
    call_ids: set[str] = set()
    for message in messages:
        if not isinstance(message, Mapping) or message.get("role") != "assistant":
            continue
        calls = message.get("tool_calls") or []
        if not isinstance(calls, (list, tuple)):
            continue
        for call in calls:
            if not isinstance(call, Mapping):
                continue
            function = call.get("function")
            if isinstance(function, Mapping):
                name = str(function.get("name") or "").strip()
            else:
                name = str(call.get("name") or "").strip()
            if name not in _TRUSTED_OMO_TOOL_NAMES:
                continue
            call_id = str(call.get("id") or call.get("call_id") or "").strip()
            if call_id:
                call_ids.add(call_id)
    return call_ids


def _extract_from_text(text: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for candidate in _candidate_json_objects(text):
        payload = _turn_facts_payload(candidate)
        if payload is not None:
            payloads.append(payload)

        nested_output = candidate.get("output")
        if isinstance(nested_output, str):
            for nested in _candidate_json_objects(nested_output):
                payload = _turn_facts_payload(nested)
                if payload is not None:
                    payloads.append(payload)
    return payloads


def _candidate_json_objects(text: str) -> list[dict[str, Any]]:
    stripped = text.strip()
    if not stripped:
        return []

    candidates = [stripped]
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        sliced = stripped[start : end + 1]
        if sliced != stripped:
            candidates.append(sliced)

    objects: list[dict[str, Any]] = []
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            objects.append(parsed)
    return objects


def _turn_facts_payload(value: dict[str, Any]) -> dict[str, Any] | None:
    if value.get("turn_facts_schema") != SCHEMA:
        return None
    facts = value.get("turn_facts")
    if not isinstance(facts, dict):
        return None
    normalized = dict(facts)
    _apply_omo_coordination(normalized)
    return normalized


def _apply_omo_coordination(facts: dict[str, Any]) -> None:
    if isinstance(facts.get("coordination"), dict):
        return

    omo = facts.get("omo")
    if not isinstance(omo, dict):
        return

    parent_session_id = str(omo.get("parent_session_id") or "")
    descendants = [str(item) for item in omo.get("descendant_session_ids") or [] if str(item)]
    parent_count = 1 if parent_session_id else 0
    descendant_count = len(descendants)
    try:
        session_created_events = int(omo.get("session_created_events") or 0)
    except (TypeError, ValueError):
        session_created_events = 0
    facts["coordination"] = {
        "observed": (parent_count + descendant_count) > 0,
        "agents": parent_count + descendant_count,
        "modes": ["omo"],
        "breakdown": {
            "omo_parent": parent_count,
            "omo_descendants": descendant_count,
            "session_created_events": session_created_events,
        },
    }
