【Spec 审核卡｜Reviewer】
verdict：SPEC_AUDIT_PASS
证据是否足够：足够；Spec/typed sidecar 已覆盖验收语义、证据要求和禁改边界。
false-success 风险：Executor 仍可能误把 JSONL audit 当通知就绪；Spec 已用 `notification_ready=false` 和 non-claims 抑制。
必须修订项：无
是否需要 zizi 判断：无
详情：
1. PA 要求已落入 Spec/sidecar：`event_stage=turn_finalized_raw`、`provisional=true`、`notification_ready=false`，且 completed 只映射为 provisional `checkout_needed`。
2. identity/provenance 已列为验收硬项：`session_id/profile/source/title_or_unknown` 必须稳定产出或显式 `unknown`，不得猜测。
3. 可验收性充分：disabled no-op、failed/partial/empty、interrupted、redaction、JSONL fail-open、finalizer hook once、allowed/forbidden 文件证明、真实 test output 与 sanitized JSONL sample 均被要求。
non_claims：no executor dispatch / no KA verified / deterministic gate not bypassed
