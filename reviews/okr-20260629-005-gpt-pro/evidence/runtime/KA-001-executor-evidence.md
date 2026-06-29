# KA-001 Executor Evidence — TurnFinalizedLifecycleEvent v1 local audit

OKR_ID: OKR-20260629-005
Round: round-001 / manual_update
Active KA: KA-001
Role: Executor
Execution status: EXECUTION_DONE (pending independent Reviewer verdict; not self-verified)

## Scope authority

Authority source read by Executor:
- `/Users/qitejia/.hermes/okr_mvp_runtime/demands/OKR-20260629-005/specs/KA-001.md`
- `/Users/qitejia/.hermes/okr_mvp_runtime/demands/OKR-20260629-005/round-001/contracts/KA-001-ka-spec.json`

No inline/forked Spec was used.

## Changed artifacts

Repo target: `/Users/qitejia/.hermes/hermes-agent`

Allowed repo artifacts changed/created:
- `agent/session_watchtower.py`
- `agent/turn_finalizer.py`
- `hermes_cli/config.py`
- `tests/agent/test_session_watchtower.py`
- `tests/agent/test_turn_finalizer_watchtower.py`

Run-dir evidence artifacts:
- `round-001/evidence/KA-001-executor-evidence.md`
- `round-001/evidence/KA-001-validation-output.txt`
- `round-001/evidence/KA-001-sample-event.jsonl`
- `round-001/evidence/KA-001-git-proof.txt`
- `round-001/evidence/KA-001-allowed-diff.patch`

## Implementation summary

Backend detected:
- `agent/turn_finalizer.py` now calls `agent.session_watchtower.emit_turn_finalized_event(...)` after the finalizer `result` dict is assembled.
- The hook receives `result`, `task_id`, `turn_id`, and `agent`.
- The hook is guarded so Watchtower failures do not change the finalizer return path.

Audit written:
- `agent/session_watchtower.py` builds a `TurnFinalizedLifecycleEvent` and appends one JSON object per line when `watchtower.enabled=true` and `watchtower.audit_log=true`.
- Relative `event_log_path` resolves under `get_hermes_home()`, preserving profile-scoped output.
- JSONL append is fail-open: exceptions are logged and return `false`.

Notification not ready:
- Every emitted event sets `event_stage="turn_finalized_raw"`, `provisional=true`, and `notification_ready=false`.
- Completed turns map to `new_state="checkout_needed"` with `requires_human=true`; this is only provisional audit state, not a notification-ready snapshot.

Identity/provenance:
- `session_id`, `profile`, `source`, and `title_or_unknown` are emitted from result/agent/session context when available.
- Missing values are emitted as the explicit marker `unknown`; no title/source/profile is inferred from UI or guessed.

Redaction:
- `final_response_excerpt`, `evidence_summary`, guardrail/result metadata, and evidence metadata are redacted before JSONL serialization.

## Validation commands and output

RED check run before implementation completion:

```text
scripts/run_tests.sh tests/agent/test_session_watchtower.py tests/agent/test_turn_finalizer_watchtower.py
Result: 2 failed, 7 passed.
Expected RED failures: missing event_stage and turn_id/title_or_unknown fields in draft implementation.
```

GREEN validation command required by Spec:

```text
scripts/run_tests.sh tests/agent/test_session_watchtower.py tests/agent/test_turn_finalizer_watchtower.py
Result: 11 tests passed, 0 failed.
```

Saved full validation output:
- `/Users/qitejia/.hermes/okr_mvp_runtime/demands/OKR-20260629-005/round-001/evidence/KA-001-validation-output.txt`

Additional focused regression checks:

```text
scripts/run_tests.sh tests/agent/test_turn_finalizer_cleanup_guard.py tests/agent/test_turn_finalizer_interrupt_alternation.py
Result: 10 tests passed, 0 failed.
```

Static diff hygiene:

```text
git diff --check -- agent/session_watchtower.py agent/turn_finalizer.py hermes_cli/config.py tests/agent/test_session_watchtower.py tests/agent/test_turn_finalizer_watchtower.py
Result: exit 0, no output.
```

## Sanitized JSONL sample

Sample artifact:
- `/Users/qitejia/.hermes/okr_mvp_runtime/demands/OKR-20260629-005/round-001/evidence/KA-001-sample-event.jsonl`

Sample generation used temp profile home:
- `/tmp/hermes-watchtower-sample.FEOdJp/home/.hermes/profiles/executor`

Important sample fields read back from JSONL:

```json
{
  "schema_version": "turn_finalized_lifecycle_event.v1",
  "event_stage": "turn_finalized_raw",
  "provisional": true,
  "notification_ready": false,
  "session_id": "sample-session-001",
  "task_id": "ta[REDACTED_TOKEN]",
  "turn_id": "turn-sample-001",
  "profile": "executor",
  "source": "cli",
  "title_or_unknown": "KA sample session",
  "new_state": "checkout_needed",
  "status": "completed",
  "requires_human": true,
  "final_response_excerpt": "Backend detected and audit written. API_TOKEN=***",
  "metadata": {
    "backend_detected": true,
    "evidence": {"password": "[REDACTED]"},
    "result_metadata": {"authorization": "[REDACTED]"}
  }
}
```

The sample generation asserted these original secret-like substrings were absent from serialized JSON:
- sample sk-like token in final response
- sample sk-like token in nested metadata
- sample password-like value in evidence metadata

## Git proof

Saved proof:
- `/Users/qitejia/.hermes/okr_mvp_runtime/demands/OKR-20260629-005/round-001/evidence/KA-001-git-proof.txt`
- `/Users/qitejia/.hermes/okr_mvp_runtime/demands/OKR-20260629-005/round-001/evidence/KA-001-allowed-diff.patch`

Observed status for allowed files:

```text
 M agent/turn_finalizer.py
 M hermes_cli/config.py
?? agent/session_watchtower.py
?? tests/agent/test_session_watchtower.py
?? tests/agent/test_turn_finalizer_watchtower.py
```

Forbidden diff check:

```text
git diff --name-only -- cli.py tui_gateway/server.py plugins/platforms/feishu/adapter.py tools/send_message_tool.py gateway/run.py gateway/config.py
Result: empty output.
```

Note: repo status still shows pre-existing untracked `.omo/` and `artifacts/` directories. They were not part of the allowed-files patch and were not used as acceptance evidence.

## Known gaps / non-claims

Known gaps:
- This KA proves backend finalizer detection plus profile-scoped local JSONL audit only.
- It does not prove Fleet Registry, Feishu delivery, interactive card/button callback, debounce/rate limit, archive policy, or notification-ready snapshots.
- It does not claim product acceptance, human acceptance, production readiness, KR closure, Spec Gate pass, or KA verification.

Proposed next state for independent review:
- `EXECUTION_DONE_PENDING_REVIEW`
- Reviewer should verify the evidence and decide KA verdict independently.
