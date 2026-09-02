"""V3 Critic: V2 최종 진단을 관찰 가능한 evidence로 독립 검증한다.

추가 Tool을 실행하지 않는다. GT/case_id/planner rationale을 입력하지 않는다.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from pydantic import BaseModel, Field

from app.cause_codes import CANONICAL_CAUSE_CODES, validate_cause_code, vocabulary_prompt_block
from app.schemas import (
    CriticIssue,
    CriticIssueType,
    CriticResult,
    ToolResult,
    V2DiagnosisResult,
)
from app.tool_use import _load_prompt, _parse_json_with_retry, apply_diagnosis_level_policy
from app.tools.evidence import filter_evidence, supporting_tool_results
from config import settings

CRITIC_DENIED_KEYS = (
    "case_id",
    "ground_truth",
    "actual_cause_code",
    "planning_trace",
    "selected_tools",
    "working_hypotheses",
    "unresolved_questions",
    "summary",
    "investigation_plan",
)

CRITIC_ALLOWED_KEYS = (
    "extracted_info",
    "final_cause_code",
    "diagnosis_level",
    "owner",
    "evidence",
    "success_tool_results",
    "canonical_causes",
    "log",
)


class CriticLLMDraft(BaseModel):
    evidence_consistent: bool = True
    issues: list[CriticIssue] = Field(default_factory=list)
    recommended_cause_code: str | None = None
    recommended_diagnosis_level: str | None = None
    revision_reason: str = ""


def success_tool_payloads(tool_results: list[ToolResult]) -> list[dict[str, Any]]:
    return [item.model_dump() for item in supporting_tool_results(tool_results)]


def build_critic_input(
    log_text: str,
    v2: V2DiagnosisResult,
) -> dict[str, Any]:
    """Allowlist only. denylist 키가 있으면 안 된다."""
    payload = {
        "extracted_info": v2.extracted_info,
        "final_cause_code": v2.final_cause_code,
        "diagnosis_level": v2.diagnosis_level,
        "owner": v2.owner,
        "evidence": list(v2.evidence or []),
        "success_tool_results": success_tool_payloads(v2.tool_results),
        "canonical_causes": sorted(CANONICAL_CAUSE_CODES),
        "log": log_text,
    }
    if set(payload) != set(CRITIC_ALLOWED_KEYS):
        raise RuntimeError("Critic 입력이 allowlist와 일치하지 않습니다.")
    if critic_input_contains_denied(payload):
        raise RuntimeError("Critic 입력에 금지 키가 포함되어 있습니다.")
    return payload


def critic_input_contains_denied(payload: dict[str, Any]) -> bool:
    return any(key in payload for key in CRITIC_DENIED_KEYS)


def _failed_errors(tool_results: list[ToolResult]) -> list[str]:
    return [
        item.error
        for item in tool_results
        if item.status != "SUCCESS" and item.error
    ]


def deterministic_issues(v2: V2DiagnosisResult) -> list[CriticIssue]:
    issues: list[CriticIssue] = []
    errors = _failed_errors(v2.tool_results)
    evidence_text = "\n".join(str(item) for item in (v2.evidence or []))
    for error in errors:
        if error and error in evidence_text:
            issues.append(
                CriticIssue(
                    issue_type=CriticIssueType.FAILED_EVIDENCE_USED,
                    description="FAILED Tool error가 최종 supporting evidence에 포함되어 있습니다.",
                    related_evidence=[error],
                    blocking=True,
                )
            )
            break

    capped = apply_diagnosis_level_policy(v2.diagnosis_level, v2.tool_results)
    if v2.diagnosis_level == "확인됨" and capped != "확인됨":
        issues.append(
            CriticIssue(
                issue_type=CriticIssueType.DIAGNOSIS_LEVEL_TOO_HIGH,
                description="SUCCESS Tool 없이 diagnosis_level이 확인됨입니다.",
                blocking=True,
            )
        )

    owner = (v2.owner or "").strip()
    if not owner:
        issues.append(
            CriticIssue(
                issue_type=CriticIssueType.OWNER_MISMATCH,
                description="owner가 비어 있습니다.",
                blocking=True,
            )
        )
    return issues


def _sanitize_recommended_cause(value: str | None) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return validate_cause_code(str(value).strip())
    except ValueError:
        return None


def alternative_supported_by_observable(
    recommended_cause: str,
    *,
    log_text: str,
    extracted_info: dict[str, Any],
    tool_results: list[ToolResult],
    related_evidence: list[str],
) -> bool:
    try:
        validate_cause_code(recommended_cause)
    except ValueError:
        return False
    success = supporting_tool_results(tool_results)
    haystack = json.dumps(
        {
            "log": log_text,
            "extracted_info": extracted_info,
            "success_tool_results": [item.model_dump() for item in success],
        },
        ensure_ascii=False,
    )
    tokens = [str(item).strip() for item in related_evidence if str(item).strip()]
    if not tokens:
        return False
    return any(token in haystack for token in tokens)


def cause_revision_allowed(
    critic: CriticResult,
    *,
    current_cause: str,
    log_text: str,
    extracted_info: dict[str, Any],
    tool_results: list[ToolResult],
) -> bool:
    types = {item.issue_type for item in critic.issues if item.blocking}
    if CriticIssueType.EVIDENCE_CONFLICT not in types:
        return False
    if CriticIssueType.BETTER_SUPPORTED_CAUSE not in types:
        return False
    recommended = _sanitize_recommended_cause(critic.recommended_cause_code)
    if not recommended or recommended == current_cause:
        return False
    related: list[str] = []
    for item in critic.issues:
        if item.issue_type == CriticIssueType.BETTER_SUPPORTED_CAUSE:
            related.extend(item.related_evidence)
        if item.issue_type == CriticIssueType.EVIDENCE_CONFLICT:
            related.extend(item.related_evidence)
    return alternative_supported_by_observable(
        recommended,
        log_text=log_text,
        extracted_info=extracted_info,
        tool_results=tool_results,
        related_evidence=related,
    )


def _merge_issues(deterministic: list[CriticIssue], llm_issues: list[CriticIssue]) -> list[CriticIssue]:
    merged: list[CriticIssue] = []
    seen: set[tuple[str, str]] = set()
    for item in [*deterministic, *llm_issues]:
        key = (item.issue_type.value, item.description)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def _finalize_critic_result(
    *,
    v2: V2DiagnosisResult,
    deterministic: list[CriticIssue],
    llm_draft: CriticLLMDraft | None,
) -> CriticResult:
    llm_issues = list(llm_draft.issues) if llm_draft is not None else []
    issues = _merge_issues(deterministic, llm_issues)
    recommended = _sanitize_recommended_cause(
        None if llm_draft is None else llm_draft.recommended_cause_code
    )
    evidence_consistent = True
    if llm_draft is not None:
        evidence_consistent = bool(llm_draft.evidence_consistent)
    if any(item.issue_type == CriticIssueType.EVIDENCE_CONFLICT for item in issues):
        evidence_consistent = False

    conflict = any(
        item.blocking and item.issue_type == CriticIssueType.EVIDENCE_CONFLICT
        for item in issues
    )
    better = any(
        item.blocking and item.issue_type == CriticIssueType.BETTER_SUPPORTED_CAUSE
        for item in issues
    )
    other_blocking = any(
        item.blocking
        and item.issue_type
        in {
            CriticIssueType.FAILED_EVIDENCE_USED,
            CriticIssueType.DIAGNOSIS_LEVEL_TOO_HIGH,
            CriticIssueType.OWNER_MISMATCH,
        }
        for item in issues
    )
    # BETTER_SUPPORTED_CAUSE only → PASS (cause 변경 금지)
    if better and not conflict and not other_blocking:
        issues = [
            item
            for item in issues
            if item.issue_type != CriticIssueType.BETTER_SUPPORTED_CAUSE
        ]
        recommended = None
        evidence_consistent = True
        better = False

    blocking = [item for item in issues if item.blocking]
    verdict = "REVISE" if blocking else "PASS"
    if verdict == "PASS":
        recommended = None
        recommended_level = None
        recommended_owner = None
        revision_reason = ""
    else:
        recommended_level = None
        if llm_draft is not None and llm_draft.recommended_diagnosis_level in {
            "추정",
            "가능성 높음",
            "확인됨",
        }:
            recommended_level = llm_draft.recommended_diagnosis_level
        recommended_owner = None
        revision_reason = ""
        if llm_draft is not None:
            revision_reason = (llm_draft.revision_reason or "")[:240]

    level_ok = not any(
        item.issue_type == CriticIssueType.DIAGNOSIS_LEVEL_TOO_HIGH for item in issues
    )
    owner_ok = not any(item.issue_type == CriticIssueType.OWNER_MISMATCH for item in issues)
    return CriticResult(
        verdict=verdict,  # type: ignore[arg-type]
        evidence_consistent=evidence_consistent,
        diagnosis_level_appropriate=level_ok,
        owner_consistent=owner_ok,
        issues=issues,
        recommended_cause_code=recommended,
        recommended_diagnosis_level=recommended_level,
        recommended_owner=recommended_owner,
        revision_reason=revision_reason,
    )


def call_critic_llm(log_text: str, v2: V2DiagnosisResult) -> CriticLLMDraft:
    payload = build_critic_input(log_text, v2)
    if critic_input_contains_denied(payload):
        raise RuntimeError("Critic 입력에 금지 키가 포함되어 있습니다.")
    system_prompt = (
        _load_prompt(settings.V3_CRITIC_PROMPT_PATH).rstrip()
        + "\n\n"
        + vocabulary_prompt_block()
        + "\n"
    )
    user_prompt = (
        "다음 관찰 가능한 정보만 사용해 검증하십시오. case_id와 Ground Truth는 없습니다.\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n"
    )
    return _parse_json_with_retry(system_prompt, user_prompt, CriticLLMDraft)


def run_critic(
    log_text: str,
    v2: V2DiagnosisResult,
    critic_fn: Callable[..., CriticLLMDraft | CriticResult] | None = None,
) -> CriticResult:
    deterministic = deterministic_issues(v2)
    runner = critic_fn or call_critic_llm
    draft = runner(log_text, v2)
    if isinstance(draft, CriticResult) and not isinstance(draft, CriticLLMDraft):
        # 테스트가 최종 CriticResult를 직접 넘긴 경우
        merged = _merge_issues(deterministic, list(draft.issues))
        rebuilt = draft.model_copy(update={"issues": merged})
        return _finalize_critic_result(
            v2=v2,
            deterministic=[],
            llm_draft=CriticLLMDraft.model_validate(rebuilt.model_dump()),
        )
    return _finalize_critic_result(v2=v2, deterministic=deterministic, llm_draft=draft)
