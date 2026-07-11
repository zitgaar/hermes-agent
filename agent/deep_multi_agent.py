"""Hermes-native Deep multi-agent worker orchestration.

This module is runtime-level. A leading ``deep:`` turn selects a protocol,
spawns independent Hermes child sessions, records durable evidence, and returns
a synthesis prompt for the parent turn. It is not the textual ``/deep`` skill
scaffold and must not be used as a silent fallback.
"""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Literal


DeepMASource = Literal["prefix", "slash_command"]
DeepProtocolKey = Literal["original_triad_critique", "taxonomy_redteam_repair_audit"]


@dataclass(frozen=True)
class DeepMARole:
    role: str
    label: str
    instruction: str
    source_slug: str
    model_provider: str | None = None
    model_name: str | None = None


@dataclass(frozen=True)
class DeepMAProtocolPlan:
    protocol_key: DeepProtocolKey
    protocol_name: str
    roles: tuple[DeepMARole, ...]


@dataclass(frozen=True)
class DeepMABranch:
    role: str
    label: str
    session_id: str | None
    returncode: int
    output: str
    error: str


@dataclass(frozen=True)
class DeepMAResult:
    protocol_key: DeepProtocolKey = "original_triad_critique"
    protocol_name: str = "Original Triad Critique"
    clean_native_ma: bool = False
    subagents: int = 0
    branches: list[DeepMABranch] = field(default_factory=list)
    degraded: str = ""
    cross_critique_completed: bool = False
    synthesis_completed: bool = False


ORIGINAL_TRIAD_ROLES: tuple[DeepMARole, ...] = (
    DeepMARole(
        role="intent_product_lens",
        label="Intent / Product Lens",
        source_slug="intent-product-lens",
        instruction=(
            "你是 Original Triad Critique 的 Intent / Product Lens 子 agent。"
            "只从用户真实意图、产品对象、需求边界、用户要解决的核心痛点分析。"
            "不要做最终综合，不要调用工具。"
        ),
    ),
    DeepMARole(
        role="architecture_product_lens",
        label="Architecture / Product Lens",
        source_slug="architecture-product-lens",
        instruction=(
            "你是 Original Triad Critique 的 Architecture / Product Lens 子 agent。"
            "只从系统结构、产品机制、角色/状态/接口边界、长期可演进性分析。"
            "不要做最终综合，不要调用工具。"
        ),
    ),
    DeepMARole(
        role="construction_execution_lens",
        label="Construction / Execution Lens",
        source_slug="construction-execution-lens",
        instruction=(
            "你是 Original Triad Critique 的 Construction / Execution Lens 子 agent。"
            "只从可实施性、执行路径、验收方式、工程/流程落地风险分析。"
            "不要做最终综合，不要调用工具。"
        ),
        model_provider="opencode-go",
        model_name="glm-5.2",
    ),
    DeepMARole(
        role="risk_claim_lens",
        label="Risk / Claim Lens",
        source_slug="risk-claim-lens",
        instruction=(
            "你是 Original Triad Critique 的 Risk / Claim Lens 子 agent。"
            "只从过度声明、证据缺口、失败模式、不能 claim 的边界分析。"
            "不要做最终综合，不要调用工具。"
        ),
    ),
)


TAXONOMY_REDTEAM_ROLES: tuple[DeepMARole, ...] = (
    DeepMARole(
        role="draft_agent",
        label="Draft Agent",
        source_slug="draft-agent",
        instruction=(
            "你是 Taxonomy-driven Draft → Red-team → Repair → Audit 的 Draft Agent。"
            "识别已有 artifact 的对象、目标、claim boundary 和进入 review 的标准。"
            "不要调用工具。"
        ),
    ),
    DeepMARole(
        role="taxonomy_red_team_agent",
        label="Taxonomy Red-team Agent",
        source_slug="red-team-agent",
        instruction=(
            "你是 Taxonomy Red-team Agent。按 T1-T12 taxonomy 审查 overclaim、"
            "under-scope、zizi burden、Feishu card-board-only、自然语言改状态、"
            "constructability 和 reviewability。不要调用工具。"
        ),
    ),
    DeepMARole(
        role="repair_agent",
        label="Repair Agent",
        source_slug="repair-agent",
        instruction=(
            "你是 Repair Agent。基于 artifact 目标和 taxonomy critique，给出修复策略、"
            "保留/拒绝理由和最终落点。不要调用工具。"
        ),
    ),
    DeepMARole(
        role="audit_agent",
        label="Audit Agent",
        source_slug="audit-agent",
        instruction=(
            "你是 Audit Agent。验证 non-claims、zizi burden、execution readiness、"
            "reviewability 和 external-review readiness。不要调用工具。"
        ),
    ),
)

_CHINESE_ARTIFACT_MARKERS = ("已有", "有一份", "送审", "产物", "草案")
_ENGLISH_ARTIFACT_PHRASE_MARKERS = (
    "fake dry-run",
    "dry-run",
    "external review",
    "external-review",
    "review packet",
    "review material",
)
_ENGLISH_ARTIFACT_WORD_MARKERS = ("spec", "artifact")
_CONTEXTUAL_DRAFT_SEED_WORD_MARKERS = ("draft", "seed")
_CONTEXTUAL_ARTIFACT_MARKERS = (
    "进入评审",
    "进入 review",
    "进入review",
    "能否进入评审",
    "能否进入 review",
    "能否进入review",
    "这份报告",
    "该报告",
    "这份结果",
    "该结果",
    "评审包",
    "审查包",
    "review 包",
    "review材料",
    "review 材料",
)
_EXISTING_ARTIFACT_BEFORE_RE = re.compile(
    r"(?:"
    r"\b(?:i|we|you|they|he|she|it)\s+(?:already\s+)?(?:have|has|had)\s+(?!to\b)"
    r"(?:a|an|the|this|that|existing|current|prepared|attached|provided)?\s*"
    r"(?:[a-z0-9_-]+\s+){0,3}$"
    r"|\b(?:existing|current|prepared|attached|provided|available|this|that|the)\s+"
    r"(?:[a-z0-9_-]+\s+){0,3}$"
    r"|已有\s*$"
    r"|有一份\s*$"
    r")"
)
_CONTEXTUAL_ARTIFACT_AFTER_RE = re.compile(
    r"^\s+(?:packet|material|artifact|spec|review\s+packet|review\s+material)\b"
)
_SESSION_ID_RE = re.compile(r"session_id:\s*([A-Za-z0-9_.:-]+)")


def _english_word_re(word: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z0-9_]){re.escape(word)}(?![a-z0-9_])")


def _has_english_word(text: str, word: str) -> bool:
    return _english_word_re(word).search(text) is not None


def _has_direct_artifact_marker(text: str) -> bool:
    if any(marker in text for marker in _CHINESE_ARTIFACT_MARKERS):
        return True
    if any(marker in text for marker in _ENGLISH_ARTIFACT_PHRASE_MARKERS):
        return True
    if any(_has_english_word(text, marker) for marker in _ENGLISH_ARTIFACT_WORD_MARKERS):
        return True
    return any(marker in text for marker in _CONTEXTUAL_ARTIFACT_MARKERS)


def _has_contextual_draft_seed_marker(text: str) -> bool:
    for marker in _CONTEXTUAL_DRAFT_SEED_WORD_MARKERS:
        for match in _english_word_re(marker).finditer(text):
            before = text[max(0, match.start() - 80) : match.start()]
            after = text[match.end() : match.end() + 80]
            if _EXISTING_ARTIFACT_BEFORE_RE.search(before):
                return True
            if _CONTEXTUAL_ARTIFACT_AFTER_RE.search(after):
                return True
    return False


def select_deep_protocol(user_instruction: str) -> DeepMAProtocolPlan:
    text = (user_instruction or "").lower()
    if _has_direct_artifact_marker(text) or _has_contextual_draft_seed_marker(text):
        return DeepMAProtocolPlan(
            protocol_key="taxonomy_redteam_repair_audit",
            protocol_name="Taxonomy-driven Draft → Red-team → Repair → Audit",
            roles=TAXONOMY_REDTEAM_ROLES,
        )
    return DeepMAProtocolPlan(
        protocol_key="original_triad_critique",
        protocol_name="Original Triad Critique",
        roles=ORIGINAL_TRIAD_ROLES,
    )


def _extract_session_id(*texts: str) -> str | None:
    for text in texts:
        if not text:
            continue
        match = _SESSION_ID_RE.search(text)
        if match:
            return match.group(1)
    return None


def build_worker_prompt(
    protocol: DeepMAProtocolPlan,
    role: DeepMARole,
    user_instruction: str,
    prior_context: str = "",
) -> str:
    prior_context_section = ""
    if prior_context:
        prior_context_section = f"上游分支上下文：\n{prior_context}\n\n"
    return (
        f"协议：{protocol.protocol_name}\n"
        f"角色：{role.label}\n\n"
        f"{role.instruction}\n\n"
        "用户原始 Deep 问题：\n"
        f"{user_instruction}\n\n"
        f"{prior_context_section}"
        "输出要求：\n"
        "- 先给一句话结论；\n"
        "- 然后给 3-6 条要点；\n"
        "- 明确自己的角色视角；\n"
        "- 只输出本角色视角，不做父级最终综合；\n"
        "- 不要调用工具；\n"
        "- 不要输出隐藏推理过程；\n"
        "- 明确 claim boundary / evidence gap，如本角色需要。"
    )


def _source_prefix(protocol: DeepMAProtocolPlan) -> str:
    if protocol.protocol_key == "original_triad_critique":
        return "deep-ma-original-triad"
    if protocol.protocol_key == "taxonomy_redteam_repair_audit":
        return "deep-ma-taxonomy"
    raise ValueError(f"unknown deep protocol: {protocol.protocol_key}")


def _role_model_overrides(protocol: DeepMAProtocolPlan) -> dict[str, dict[str, str]]:
    return {
        role.role: {"provider": role.model_provider, "model": role.model_name}
        for role in protocol.roles
        if role.model_provider and role.model_name
    }


def _worker_command(
    protocol: DeepMAProtocolPlan,
    role: DeepMARole,
    user_instruction: str,
    prior_context: str = "",
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "hermes_cli.main",
        "chat",
        "--cli",
        "-Q",
        "--ignore-rules",
        "--max-turns",
        "1",
        "--toolsets",
        "none",
        "--source",
        f"{_source_prefix(protocol)}-{role.source_slug}",
        "-q",
        build_worker_prompt(protocol, role, user_instruction, prior_context=prior_context),
    ]
    if role.model_provider and role.model_name:
        insert_at = command.index("--ignore-rules")
        command[insert_at:insert_at] = ["--provider", role.model_provider, "--model", role.model_name]
    return command


def _run_one_worker(
    protocol: DeepMAProtocolPlan,
    role: DeepMARole,
    user_instruction: str,
    timeout_seconds: int,
    prior_context: str = "",
    parent_session_id: str = "",
) -> DeepMABranch:
    env = os.environ.copy()
    env["HERMES_DEEP_MA_WORKER"] = "1"
    env["HERMES_DEEP_MA_DISABLE"] = "1"
    if parent_session_id:
        env["HERMES_DEEP_MA_PARENT_SESSION_ID"] = parent_session_id
        env["HERMES_DEEP_MA_ROLE"] = role.role
        env["HERMES_DEEP_MA_PROTOCOL"] = protocol.protocol_key
    if role.model_provider and role.model_name:
        env["HERMES_DEEP_MA_ROLE_PROVIDER"] = role.model_provider
        env["HERMES_DEEP_MA_ROLE_MODEL"] = role.model_name
    try:
        completed = subprocess.run(
            _worker_command(protocol, role, user_instruction, prior_context=prior_context),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            env=env,
        )
        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        return DeepMABranch(
            role=role.role,
            label=role.label,
            session_id=_extract_session_id(stderr, stdout),
            returncode=int(completed.returncode),
            output=stdout,
            error=stderr,
        )
    except subprocess.TimeoutExpired as exc:
        timeout_stdout = str(exc.stdout) if isinstance(exc.stdout, str) else ""
        return DeepMABranch(
            role=role.role,
            label=role.label,
            session_id=None,
            returncode=124,
            output=timeout_stdout.strip(),
            error=f"timeout after {timeout_seconds}s",
        )
    except Exception as exc:
        return DeepMABranch(
            role=role.role,
            label=role.label,
            session_id=None,
            returncode=1,
            output="",
            error=str(exc),
        )


def _branch_context(branches: list[DeepMABranch]) -> str:
    if not branches:
        return ""
    return "\n\n".join(
        f"## Prior branch: {branch.label}\nrole={branch.role}\nsession_id={branch.session_id or 'unknown'}\n\n{branch.output or '[EMPTY]'}"
        for branch in branches
    )


def _run_parallel_roles(
    protocol: DeepMAProtocolPlan,
    user_instruction: str,
    timeout_seconds: int,
    parent_session_id: str = "",
) -> list[DeepMABranch]:
    branches_by_role: dict[str, DeepMABranch] = {}
    with ThreadPoolExecutor(max_workers=max(1, len(protocol.roles))) as pool:
        futures = {
            pool.submit(
                _run_one_worker,
                protocol,
                role,
                user_instruction,
                timeout_seconds,
                "",
                parent_session_id,
            ): role
            for role in protocol.roles
        }
        for future in as_completed(futures):
            role = futures[future]
            branches_by_role[role.role] = future.result()
    return [branches_by_role[role.role] for role in protocol.roles]


def _run_taxonomy_sequence(
    protocol: DeepMAProtocolPlan,
    user_instruction: str,
    timeout_seconds: int,
    parent_session_id: str = "",
) -> list[DeepMABranch]:
    branches: list[DeepMABranch] = []
    for role in protocol.roles:
        branches.append(
            _run_one_worker(
                protocol,
                role,
                user_instruction,
                timeout_seconds,
                prior_context=_branch_context(branches),
                parent_session_id=parent_session_id,
            )
        )
    return branches


def _link_child_sessions_to_parent(
    *,
    parent_session_id: str,
    protocol: DeepMAProtocolPlan,
    branches: list[DeepMABranch],
) -> int:
    """Best-effort SQLite lineage link for Deep MA worker sessions."""
    child_rows = [branch for branch in branches if branch.session_id]
    if not parent_session_id or not child_rows:
        return 0
    updated = 0
    for attempt in range(20):
        try:
            from hermes_state import SessionDB

            db = SessionDB()
            source_by_role = {
                role.role: f"{_source_prefix(protocol)}-{role.source_slug}"
                for role in protocol.roles
            }
            route_by_role = {
                role.role: {"provider": role.model_provider, "model": role.model_name}
                for role in protocol.roles
            }

            def _do(conn: sqlite3.Connection) -> int:
                count = 0
                for branch in child_rows:
                    source = source_by_role.get(branch.role, _source_prefix(protocol))
                    route = route_by_role.get(branch.role) or {}
                    if route.get("provider") and route.get("model"):
                        cur = conn.execute(
                            """
                            UPDATE sessions
                            SET parent_session_id = COALESCE(parent_session_id, ?),
                                source = CASE WHEN source IS NULL OR source = 'unknown' THEN ? ELSE source END,
                                model_config = json_set(
                                    COALESCE(model_config, '{}'),
                                    '$._delegate_from', ?,
                                    '$._deep_ma_from', ?,
                                    '$._deep_ma_role', ?,
                                    '$._deep_ma_protocol', ?,
                                    '$._deep_ma_provider', ?,
                                    '$._deep_ma_model', ?
                                )
                            WHERE id = ?
                            """,
                            (
                                parent_session_id,
                                source,
                                parent_session_id,
                                parent_session_id,
                                branch.role,
                                protocol.protocol_key,
                                route["provider"],
                                route["model"],
                                branch.session_id,
                            ),
                        )
                    else:
                        cur = conn.execute(
                            """
                            UPDATE sessions
                            SET parent_session_id = COALESCE(parent_session_id, ?),
                                source = CASE WHEN source IS NULL OR source = 'unknown' THEN ? ELSE source END,
                                model_config = json_set(
                                    COALESCE(model_config, '{}'),
                                    '$._delegate_from', ?,
                                    '$._deep_ma_from', ?,
                                    '$._deep_ma_role', ?,
                                    '$._deep_ma_protocol', ?
                                )
                            WHERE id = ?
                            """,
                            (
                                parent_session_id,
                                source,
                                parent_session_id,
                                parent_session_id,
                                branch.role,
                                protocol.protocol_key,
                                branch.session_id,
                            ),
                        )
                    count += int(cur.rowcount or 0)
                return count

            try:
                updated = max(updated, int(db._execute_write(_do) or 0))
            finally:
                try:
                    db.close()
                except Exception:
                    pass
            if updated >= len(child_rows):
                return updated
        except Exception:
            pass
        if attempt < 19:
            time.sleep(0.1)
    return updated


def _record_deep_event(*, parent_session_id: str, source: str, status: str, payload: dict) -> None:
    try:
        from agent.mechanism_ledger import record_mechanism_event

        record_mechanism_event(
            parent_session_id,
            {
                "mechanism": "deep",
                "source": source,
                "status": status,
                "payload": payload,
            },
        )
    except Exception:
        pass


def run_deep_multi_agent(
    *,
    user_instruction: str,
    parent_session_id: str,
    source: DeepMASource,
    timeout_seconds: int = 180,
    protocol_plan: DeepMAProtocolPlan | None = None,
) -> DeepMAResult:
    """Run independent Hermes child agents for a Deep turn and record evidence."""
    protocol = protocol_plan or select_deep_protocol(user_instruction)
    if protocol.protocol_key == "taxonomy_redteam_repair_audit":
        branches = _run_taxonomy_sequence(
            protocol,
            user_instruction,
            timeout_seconds,
            parent_session_id=parent_session_id,
        )
    else:
        branches = _run_parallel_roles(
            protocol,
            user_instruction,
            timeout_seconds,
            parent_session_id=parent_session_id,
        )

    clean = bool(branches) and all(
        branch.returncode == 0 and branch.output and branch.session_id for branch in branches
    )
    degraded = "" if clean else "DEGRADED=partial_workers_failed"
    result = DeepMAResult(
        protocol_key=protocol.protocol_key,
        protocol_name=protocol.protocol_name,
        clean_native_ma=clean,
        subagents=len(branches),
        branches=branches,
        degraded=degraded,
        cross_critique_completed=clean and protocol.protocol_key == "original_triad_critique",
        synthesis_completed=clean,
    )

    linked_child_sessions = _link_child_sessions_to_parent(
        parent_session_id=parent_session_id,
        protocol=protocol,
        branches=branches,
    )

    payload = {
        "key": "skill:deep",
        "kind": "multi_agent",
        "name": "deep",
        "phase": "workers",
        "protocol": protocol.protocol_name,
        "protocol_key": protocol.protocol_key,
        "wrong_object_replaced": True,
        "subagents": len(branches),
        "clean_native_ma": clean,
        "degraded": degraded,
        "roles": [branch.role for branch in branches],
        "child_session_ids": [branch.session_id for branch in branches],
        "linked_child_sessions": linked_child_sessions,
        "role_model_overrides": _role_model_overrides(protocol),
    }
    _record_deep_event(
        parent_session_id=parent_session_id,
        source=source,
        status="workers.completed" if clean else "workers.degraded",
        payload=payload,
    )
    return result


def child_session_ids(result: DeepMAResult) -> list[str]:
    return [branch.session_id for branch in result.branches if branch.session_id]


def deep_turn_facts(result: DeepMAResult, *, route_actual: str | None = None) -> dict:
    """Build TurnReceipt facts from a real Deep runtime result.

    ``Deep ✓`` is reserved for clean runtime results with child-session
    evidence. Degraded results still record route intent, but ``deep.observed``
    stays false so renderers cannot claim success.
    """
    ids = child_session_ids(result)
    clean = bool(result.clean_native_ma and ids)
    route = route_actual or ("deep/runtime" if clean else "deep/runtime-degraded")
    return {
        "route": {"actual": route, "reason": "user_requested_deep"},
        "deep": {
            "observed": clean,
            "protocol_key": result.protocol_key if clean else None,
            "child_session_ids": ids if clean else [],
        },
        "coordination": {
            "observed": clean,
            "agents": len(ids) if clean else 0,
            "modes": ["deep"] if clean else [],
            "breakdown": {"deep_children": len(ids)} if clean else {},
        },
        "evidence": {
            "sources": ["deep_runtime_ledger"] if clean else [],
        },
    }


def deep_unavailable_turn_facts(reason: str) -> dict:
    return {
        "route": {"actual": "deep/unavailable", "reason": reason or "deep_runtime_unavailable"},
        "deep": {"observed": False, "protocol_key": None, "child_session_ids": []},
        "coordination": {"observed": False, "agents": 0, "modes": [], "breakdown": {}},
        "evidence": {"sources": []},
    }


def build_deep_ma_synthesis_prompt(
    user_instruction: str,
    result: DeepMAResult,
    *,
    skill_prompt: str = "",
) -> str:
    branch_sections: list[str] = []
    for branch in result.branches:
        status = "ok" if branch.returncode == 0 else f"failed:{branch.returncode}"
        branch_sections.append(
            f"## {branch.label} 子 agent\n"
            f"role={branch.role}\n"
            f"session_id={branch.session_id or 'unknown'}\n"
            f"status={status}\n\n"
            f"输出：\n{branch.output or '[EMPTY]'}\n\n"
            f"错误/诊断：\n{branch.error or '[none]'}"
        )

    receipt = (
        "Deep Multi-Agent Runtime Receipt\n"
        f"- protocol: {result.protocol_name}\n"
        f"- protocol_key: {result.protocol_key}\n"
        f"- native_delegation_used: true\n"
        f"- clean_native_ma: {str(result.clean_native_ma).lower()}\n"
        f"- subagents={result.subagents}\n"
        f"- degraded: {result.degraded or 'none'}\n"
        f"- cross_critique_completed: {str(result.cross_critique_completed).lower()}\n"
        f"- synthesis_completed: {str(result.synthesis_completed).lower()}\n"
    )

    if result.protocol_key == "original_triad_critique":
        synthesis_operation = (
            "协议/综合操作：Original Triad Critique — compressed cross-critique\n"
            "请在四个 Lens 之间做压缩交叉批判与综合：Intent / Product Lens、"
            "Architecture / Product Lens、Construction / Execution Lens、Risk / Claim Lens。"
        )
        merge_instruction = (
            "- 按 Original Triad Critique 的 compressed cross-critique 综合四个 Lens 的判断、冲突、"
            "互相校正和最终边界；\n"
        )
    else:
        synthesis_operation = f"协议/综合操作：{result.protocol_name} 的父级综合"
        merge_instruction = f"- 按 {result.protocol_name} 合成各子 agent 输出；\n"

    skill_section = f"{skill_prompt}\n\n" if str(skill_prompt or "").strip() else ""
    return (
        skill_section
        + "# Deep runtime multi-agent evidence\n\n"
        f"用户原始问题：\n{user_instruction}\n\n"
        f"{receipt}\n"
        f"{synthesis_operation}\n\n"
        "下面是真实独立 Hermes 子 agent 的分支输出。请你作为父级 Synthesizer，"
        "基于这些输出给 zizi 一个压缩后的最终答案。\n\n"
        "要求：\n"
        "- 必须承认已经运行真实子 agent；\n"
        "- 不要声称没有真实子 agent；\n"
        "- 如果 degraded 不是 none，要明确说哪一部分降级；\n"
        "- 先给人话结论；\n"
        f"{merge_instruction}"
        "- 保留 claim boundary；\n"
        "- 不要输出原始长日志。\n\n"
        + "\n\n---\n\n".join(branch_sections)
    )
