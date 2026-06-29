# Known Issues and Optimization Requests

## Problems Hermes faced in this run

1. **State surface drift**
   - Canonical state once showed healthy/active while PM output was effectively blocked.
   - Later PM final briefly produced `KA_VERIFIED` evidence but canonical state became `blocked` due to adapter normalization.

2. **Display-friendly sidecars vs typed contracts**
   - PM and profiles naturally emitted human-readable or display-shaped fields.
   - Typed runtime expected narrower machine shapes.
   - The bridge had to normalize `requirements`, dispatch baton, and `next_state` forms.

3. **Executor completion vs process return**
   - Executor wrote real code/evidence/tests.
   - Profile return/card IO stalled after evidence completion.
   - Recovery required independent Reviewer judgment over artifacts.

4. **Artifact workflow vs true Kanban scheduler**
   - The Kanban workflow captured steps and gates, but did not yet behave like a robust external board with retry/requeue semantics.

5. **State JSON pollution**
   - Long rendered text in `last_pm_final` polluted strict JSON parsing until repaired.

## Future optimization requests for GPT Pro to assess

1. Should OKR Room lifecycle use event-sourced append-only state instead of mutable `OKR_STATE.json`?
2. Should all profile outputs be forced through schemas before any human card is rendered?
3. Should Kanban be upgraded from artifact ledger to durable queue with explicit retry/lease/dead-letter semantics?
4. Should Executor be required to produce structured `executor_result` sidecar before Reviewer can run?
5. Should multi-agent execution be a separate explicit backend contract rather than inferred from logs?
6. What is the minimum acceptance contract before this flow can be trusted for higher-stakes repo changes?

## Specific review asks

- Identify which failures are fundamental architecture issues vs fixable adapter/schema bugs.
- Judge whether PA Gate is worth the added latency.
- Recommend the next smallest hardening milestone.
