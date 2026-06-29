from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from agent import session_watchtower as watchtower


class _Agent:
    platform = "cli"
    session_id = "agent-session-1"
    model = "stub/model"
    provider = "stub-provider"

    def __init__(self, *, title: str | None = None, source: str | None = "cli"):
        self._session_db = _SessionDB(title)
        self._watchtower_source = source


class _SessionDB:
    def __init__(self, title: str | None):
        self._title = title

    def get_session_title(self, session_id: str) -> str | None:
        assert session_id == "session-123"
        return self._title


def _profile_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    hermes_home = home / ".hermes" / "profiles" / "executor"
    hermes_home.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    return hermes_home


def _completed_result(**overrides):
    result = {
        "session_id": "session-123",
        "completed": True,
        "failed": False,
        "partial": False,
        "interrupted": False,
        "turn_exit_reason": "text_response(finish_reason=stop)",
        "final_response": "Done. SECRET_TOKEN=fake_secret_support_3456",
        "model": "stub/model",
        "provider": "stub-provider",
        "api_calls": 2,
        "guardrail": {"api_key": "fake_secret_guardrail_7890"},
        "metadata": {"authorization": "Bearer fake_secret_metadata_7890"},
        "evidence": {"password": "fake_password_value"},
    }
    result.update(overrides)
    return result


def _read_jsonl(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    return json.loads(lines[0])


def test_emit_disabled_default_does_not_create_jsonl(tmp_path, monkeypatch):
    hermes_home = _profile_home(tmp_path, monkeypatch)
    monkeypatch.setattr("hermes_cli.config.load_config", lambda: {})

    wrote = watchtower.emit_turn_finalized_event(
        result=_completed_result(),
        task_id="task-123",
        turn_id="turn-123",
        agent=_Agent(),
    )

    assert wrote is False
    assert not (hermes_home / watchtower.DEFAULT_EVENT_LOG_PATH).exists()


def test_completed_turn_writes_provisional_checkout_needed_event(tmp_path, monkeypatch):
    hermes_home = _profile_home(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {
            "watchtower": {
                "enabled": True,
                "audit_log": True,
                "event_log_path": "audit/session_events.jsonl",
                "max_excerpt_chars": 80,
                "redact": True,
            }
        },
    )

    wrote = watchtower.emit_turn_finalized_event(
        result=_completed_result(final_response="Ready for checkout."),
        task_id="task-123",
        turn_id="turn-123",
        agent=_Agent(title="Important session"),
    )

    assert wrote is True
    event = _read_jsonl(hermes_home / "audit" / "session_events.jsonl")
    assert event["schema_version"] == watchtower.SCHEMA_VERSION
    assert event["event_stage"] == "turn_finalized_raw"
    assert event["provisional"] is True
    assert event["notification_ready"] is False
    assert event["session_id"] == "session-123"
    assert event["task_id"] == "task-123"
    assert event["turn_id"] == "turn-123"
    assert event["profile"] == "executor"
    assert event["source"] == "cli"
    assert event["title_or_unknown"] == "Important session"
    assert event["new_state"] == "checkout_needed"
    assert event["status"] == "completed"
    assert event["requires_human"] is True


def test_identity_provenance_uses_explicit_unknown_without_guessing(tmp_path, monkeypatch):
    _profile_home(tmp_path, monkeypatch)
    event = watchtower.build_turn_finalized_event(
        result={
            "completed": True,
            "failed": False,
            "partial": False,
            "interrupted": False,
            "final_response": "Done",
        },
        task_id=None,
        turn_id=None,
        agent=object(),
        watchtower_config=watchtower.WatchtowerConfig(redact=True),
    )

    assert event.session_id == watchtower.UNKNOWN_CONTEXT
    assert event.task_id == watchtower.UNKNOWN_CONTEXT
    assert event.turn_id == watchtower.UNKNOWN_CONTEXT
    assert event.source == watchtower.UNKNOWN_CONTEXT
    assert event.title_or_unknown == watchtower.UNKNOWN_CONTEXT


@pytest.mark.parametrize(
    ("overrides", "expected_state", "expected_status"),
    [
        ({"completed": False, "failed": True, "final_response": "failed"}, "failed", "failed"),
        ({"completed": False, "partial": True, "final_response": "partial"}, "failed", "failed"),
        ({"completed": True, "final_response": ""}, "failed", "failed"),
        ({"completed": False, "interrupted": True, "final_response": ""}, "interrupted", "interrupted"),
    ],
)
def test_failure_partial_empty_and_interrupted_state_mapping(overrides, expected_state, expected_status):
    event = watchtower.build_turn_finalized_event(
        result=_completed_result(**overrides),
        task_id="task-123",
        turn_id="turn-123",
        agent=_Agent(),
        watchtower_config=watchtower.WatchtowerConfig(redact=True),
    )

    assert event.new_state == expected_state
    assert event.status == expected_status
    assert event.new_state != "checkout_needed"


def test_redacts_final_response_evidence_and_nested_metadata(tmp_path, monkeypatch):
    _profile_home(tmp_path, monkeypatch)
    secret = "fake_secret_support_3456"
    guardrail_secret = "fake_secret_guardrail_7890"
    metadata_secret = "fake_secret_metadata_7890"
    evidence_secret = "fake_password_value"

    event = watchtower.build_turn_finalized_event(
        result=_completed_result(),
        task_id="task-123",
        turn_id="turn-123",
        agent=_Agent(),
        watchtower_config=watchtower.WatchtowerConfig(redact=True),
    )
    serialized = json.dumps(asdict(event), sort_keys=True)

    assert secret not in serialized
    assert guardrail_secret not in serialized
    assert metadata_secret not in serialized
    assert evidence_secret not in serialized
    assert "[REDACTED" in serialized or "***" in serialized


def test_append_jsonl_event_fails_open_on_write_error(monkeypatch):
    event = watchtower.build_turn_finalized_event(
        result=_completed_result(final_response="Done"),
        task_id="task-123",
        turn_id="turn-123",
        agent=_Agent(),
        watchtower_config=watchtower.WatchtowerConfig(redact=True),
    )

    def boom(*args, **kwargs):
        raise OSError("disk is read-only")

    monkeypatch.setattr(Path, "open", boom)

    assert watchtower.append_jsonl_event(event, path="/tmp/watchtower-forbidden.jsonl") is False
