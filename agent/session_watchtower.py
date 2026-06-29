from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from agent.redact import redact_sensitive_text
from hermes_constants import get_hermes_home

SCHEMA_VERSION: Final = "turn_finalized_lifecycle_event.v1"
DEFAULT_EVENT_LOG_PATH: Final = "watchtower/session_events.jsonl"
DEFAULT_MAX_EXCERPT_CHARS: Final = 500
UNKNOWN_CONTEXT: Final = "unknown"

logger = logging.getLogger(__name__)

JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True, slots=True)
class WatchtowerConfig:
    enabled: bool = False
    audit_log: bool = True
    event_log_path: str = DEFAULT_EVENT_LOG_PATH
    max_excerpt_chars: int = DEFAULT_MAX_EXCERPT_CHARS
    redact: bool = True


@dataclass(frozen=True, slots=True)
class TurnFinalizedLifecycleEvent:
    event_id: str
    schema_version: str
    event_stage: str
    provisional: bool
    notification_ready: bool
    session_id: str
    task_id: str
    turn_id: str
    profile: str
    source: str
    title_or_unknown: str
    previous_state: str
    new_state: str
    status: str
    turn_exit_reason: str
    completed: bool
    failed: bool
    interrupted: bool
    event_at: str
    duration_ms: int | None
    final_response_excerpt: str
    evidence_summary: str
    requires_human: bool
    action_needed: str
    confidence: str
    metadata: dict[str, JsonValue] = field(default_factory=dict)


def parse_watchtower_config(config: dict[str, JsonValue]) -> WatchtowerConfig:
    raw_watchtower = config.get("watchtower")
    if not isinstance(raw_watchtower, dict):
        return WatchtowerConfig()

    enabled = raw_watchtower.get("enabled") is True
    audit_log = raw_watchtower.get("audit_log") is not False
    redact = raw_watchtower.get("redact") is not False
    event_log_path = raw_watchtower.get("event_log_path")
    max_excerpt_chars = raw_watchtower.get("max_excerpt_chars")
    return WatchtowerConfig(
        enabled=enabled,
        audit_log=audit_log,
        event_log_path=(
            event_log_path
            if isinstance(event_log_path, str) and event_log_path.strip()
            else DEFAULT_EVENT_LOG_PATH
        ),
        max_excerpt_chars=(
            max_excerpt_chars
            if (
                isinstance(max_excerpt_chars, int)
                and not isinstance(max_excerpt_chars, bool)
                and max_excerpt_chars > 0
            )
            else DEFAULT_MAX_EXCERPT_CHARS
        ),
        redact=redact,
    )


def build_turn_finalized_event(
    *,
    result: dict[str, JsonValue],
    task_id: str | None,
    turn_id: str | None,
    agent,
    watchtower_config: WatchtowerConfig | None = None,
) -> TurnFinalizedLifecycleEvent:
    config = watchtower_config or WatchtowerConfig()
    interrupted = result.get("interrupted") is True
    turn_exit_reason = _as_text(result.get("turn_exit_reason"))
    final_response = _as_text(result.get("final_response"))
    failed = (
        result.get("failed") is True
        or result.get("partial") is True
        or (not interrupted and not final_response.strip())
    )
    completed = result.get("completed") is True and not failed and not interrupted
    session_id = _session_id(result, agent)

    new_state, status, action_needed = _map_turn_state(
        completed=completed,
        failed=failed,
        interrupted=interrupted,
        final_response=final_response,
    )
    metadata: dict[str, JsonValue] = {
        "backend_detected": True,
        "platform": _platform(agent),
        "model": _as_text(result.get("model")),
        "provider": _as_text(result.get("provider")),
        "api_calls": _as_int(result.get("api_calls")),
        "response_previewed": result.get("response_previewed") is True,
        "cleanup_error_count": _cleanup_error_count(result.get("cleanup_errors")),
    }
    guardrail = result.get("guardrail")
    if isinstance(guardrail, dict):
        metadata["guardrail"] = _redacted_json_value(guardrail, enabled=config.redact)
    result_metadata = result.get("metadata")
    if isinstance(result_metadata, dict):
        metadata["result_metadata"] = _redacted_json_value(
            result_metadata,
            enabled=config.redact,
        )
    result_evidence = result.get("evidence")
    if (
        isinstance(result_evidence, (str, int, float, bool, list, dict))
        or result_evidence is None
    ):
        metadata["evidence"] = _redacted_json_value(result_evidence, enabled=config.redact)

    excerpt = _truncate(final_response, config.max_excerpt_chars)
    evidence = _build_evidence_summary(
        turn_exit_reason=turn_exit_reason,
        completed=completed,
        failed=failed,
        interrupted=interrupted,
        final_response=final_response,
    )
    if config.redact:
        excerpt = redact_sensitive_text(excerpt, force=True)
        evidence = redact_sensitive_text(evidence, force=True)

    return TurnFinalizedLifecycleEvent(
        event_id=str(uuid.uuid4()),
        schema_version=SCHEMA_VERSION,
        event_stage="turn_finalized_raw",
        provisional=True,
        notification_ready=False,
        session_id=session_id,
        task_id=task_id or UNKNOWN_CONTEXT,
        turn_id=turn_id or UNKNOWN_CONTEXT,
        profile=_profile(result, agent),
        source=_source(result, agent),
        title_or_unknown=_title_or_unknown(result, agent, session_id),
        previous_state=UNKNOWN_CONTEXT,
        new_state=new_state,
        status=status,
        turn_exit_reason=turn_exit_reason or UNKNOWN_CONTEXT,
        completed=completed,
        failed=failed,
        interrupted=interrupted,
        event_at=datetime.now(UTC).isoformat(),
        duration_ms=_duration_ms(result),
        final_response_excerpt=excerpt,
        evidence_summary=evidence,
        requires_human=True,
        action_needed=action_needed,
        confidence="raw_turn_finalized",
        metadata=metadata,
    )


def append_jsonl_event(
    event: TurnFinalizedLifecycleEvent,
    *,
    path: str | Path | None = None,
) -> bool:
    try:
        event_path = _event_path(path)
        event_path.parent.mkdir(parents=True, exist_ok=True)
        with event_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(asdict(event), ensure_ascii=False, separators=(",", ":"))
            )
            handle.write("\n")
        return True
    except Exception as exc:  # noqa: BROAD_EXCEPT_OK
        logger.warning("watchtower JSONL append failed: %s", exc)
        return False


def emit_turn_finalized_event(
    *,
    result: dict[str, JsonValue],
    task_id: str | None,
    turn_id: str | None,
    agent,
) -> bool:
    try:
        from hermes_cli.config import load_config

        watchtower_config = parse_watchtower_config(load_config())
        if not (watchtower_config.enabled and watchtower_config.audit_log):
            return False
        event = build_turn_finalized_event(
            result=result,
            task_id=task_id,
            turn_id=turn_id,
            agent=agent,
            watchtower_config=watchtower_config,
        )
        return append_jsonl_event(event, path=watchtower_config.event_log_path)
    except Exception as exc:  # noqa: BROAD_EXCEPT_OK
        logger.warning("watchtower turn-finalized emit failed: %s", exc)
        return False


def _event_path(path: str | Path | None) -> Path:
    if path is None:
        return get_hermes_home() / DEFAULT_EVENT_LOG_PATH
    raw_path = Path(path)
    if raw_path.is_absolute():
        return raw_path
    return get_hermes_home() / raw_path


def _session_id(result: dict[str, JsonValue], agent) -> str:
    for value in (result.get("session_id"), getattr(agent, "session_id", None)):
        text = _as_text(value).strip()
        if text:
            return text
    return UNKNOWN_CONTEXT


def _profile(result: dict[str, JsonValue], agent) -> str:
    for value in (
        result.get("profile"),
        getattr(agent, "profile", None),
        getattr(agent, "profile_name", None),
        getattr(agent, "_profile", None),
        getattr(agent, "_profile_name", None),
    ):
        text = _as_text(value).strip()
        if text:
            return text
    try:
        from hermes_cli.profiles import get_active_profile_name

        profile = get_active_profile_name()
        if isinstance(profile, str) and profile.strip():
            return profile.strip()
    except Exception:
        pass
    return UNKNOWN_CONTEXT


def _source(result: dict[str, JsonValue], agent) -> str:
    for value in (
        result.get("source"),
        getattr(agent, "_watchtower_source", None),
        getattr(agent, "source", None),
        getattr(agent, "session_source", None),
        getattr(agent, "_session_source", None),
    ):
        text = _as_text(value).strip()
        if text:
            return text
    try:
        from gateway.session_context import get_session_env

        env_source = get_session_env("HERMES_SESSION_SOURCE", "")
        if isinstance(env_source, str) and env_source.strip():
            return env_source.strip()
    except Exception:
        pass
    platform = _platform(agent)
    if platform != UNKNOWN_CONTEXT:
        return platform
    return UNKNOWN_CONTEXT


def _title_or_unknown(result: dict[str, JsonValue], agent, session_id: str) -> str:
    for value in (
        result.get("title_or_unknown"),
        result.get("title"),
        getattr(agent, "title_or_unknown", None),
        getattr(agent, "session_title", None),
        getattr(agent, "_session_title", None),
    ):
        text = _as_text(value).strip()
        if text:
            return text
    session_db = getattr(agent, "_session_db", None) or getattr(agent, "session_db", None)
    if session_db is not None and session_id != UNKNOWN_CONTEXT:
        try:
            title = session_db.get_session_title(session_id)
            text = _as_text(title).strip()
            if text:
                return text
        except Exception:
            pass
    return UNKNOWN_CONTEXT


def _duration_ms(result: dict[str, JsonValue]) -> int | None:
    value = result.get("duration_ms")
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    start = result.get("started_at_ms")
    end = result.get("ended_at_ms")
    if (
        isinstance(start, int)
        and not isinstance(start, bool)
        and isinstance(end, int)
        and not isinstance(end, bool)
        and end >= start
    ):
        return end - start
    return None


def _map_turn_state(
    *,
    completed: bool,
    failed: bool,
    interrupted: bool,
    final_response: str,
) -> tuple[str, str, str]:
    if interrupted:
        return "interrupted", "interrupted", "checkout interrupted turn"
    if failed or not final_response.strip():
        return "failed", "failed", "checkout failure and decide next action"
    if completed:
        return "checkout_needed", "completed", "checkout result"
    return "failed", "failed", "checkout incomplete turn and decide next action"


def _build_evidence_summary(
    *,
    turn_exit_reason: str,
    completed: bool,
    failed: bool,
    interrupted: bool,
    final_response: str,
) -> str:
    response_chars = len(final_response)
    return (
        f"turn_exit_reason={turn_exit_reason or UNKNOWN_CONTEXT}; "
        f"completed={completed}; failed={failed}; interrupted={interrupted}; "
        f"final_response_chars={response_chars}"
    )


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _as_text(value: JsonValue) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _as_int(value: JsonValue) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _cleanup_error_count(value: JsonValue) -> int:
    if isinstance(value, list):
        return len(value)
    return 0


def _platform(agent) -> str:
    value = getattr(agent, "platform", None)
    if isinstance(value, str) and value.strip():
        return value
    return UNKNOWN_CONTEXT


def _redacted_json_value(
    value: JsonValue,
    *,
    enabled: bool,
    sensitive_context: bool = False,
) -> JsonValue:
    if enabled and sensitive_context and value is not None:
        return "[REDACTED]"
    match value:
        case str():
            return redact_sensitive_text(value, force=True) if enabled else value
        case int() | float() | bool() | None:
            return value
        case list():
            return [_redacted_json_value(item, enabled=enabled) for item in value]
        case dict():
            return {
                key: _redacted_json_value(
                    item,
                    enabled=enabled,
                    sensitive_context=_is_sensitive_metadata_key(key),
                )
                for key, item in value.items()
            }


def _is_sensitive_metadata_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    key_lc = key.strip().lower().replace("-", "_").replace(" ", "_")
    return any(
        marker in key_lc
        for marker in (
            "api_key",
            "apikey",
            "token",
            "password",
            "passwd",
            "secret",
            "authorization",
            "cookie",
            "credential",
            "private_key",
        )
    )
