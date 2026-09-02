"""V3 Critic / Reflection. Producer는 동결된 diagnose_v2()다. 추가 Tool을 실행하지 않는다."""

from __future__ import annotations

import json
from typing import Callable

from pydantic import BaseModel, field_validator

from app.cause_codes import CAUSE_CODE_NAMES, validate_cause_code, vocabulary_prompt_block
from app.critic import (
    cause_revision_allowed,
    run_critic,
)
from app.planning import diagnose_v2
from app.schemas import (
    CriticResult,
    V2DiagnosisResult,
    V3DiagnosisResult,
)
from app.tool_use import _load_prompt, _parse_json_with_retry, apply_diagnosis_level_policy
from app.tools.evidence import filter_evidence, supporting_tool_results
from config import settings

MAX_CRITIC_CALLS = 1
MAX_REVISION_CALLS = 1


class RevisionDraft(BaseModel):
    summary: str = ""
    final_cause_code: str
    final_cause_name: str = ""
    diagnosis_level: str = "추정"
    owner: str = ""
    evidence: list[str]
    limitations: list[str]
    recommended_actions: list[str] = []

    @field_validator("final_cause_code")
    @classmethod
    def canonical_code(cls, value: str) -> str:
        return validate_cause_code(value.strip())


def _v2_snapshot(v2: V2DiagnosisResult) -> V2DiagnosisResult:
    return v2.model_copy(deep=True)


def _structured_issues(critic: CriticResult) -> list[dict]:
    rows = []
    for item in critic.issues:
        rows.append(
            {
                "issue_type": item.issue_type.value,
                "description": item.description,
                "related_evidence": list(item.related_evidence),
                "blocking": item.blocking,
            }
        )
    return rows


def call_revision_llm(
    log_text: str,
    v2: V2DiagnosisResult,
    critic: CriticResult,
) -> RevisionDraft:
    success = [item.model_dump() for item in supporting_tool_results(v2.tool_results)]
    payload = {
        "extracted_info": v2.extracted_info,
        "v2_final_cause_code": v2.final_cause_code,
        "v2_diagnosis_level": v2.diagnosis_level,
        "v2_owner": v2.owner,
        "v2_evidence": list(v2.evidence or []),
        "v2_limitations": list(v2.limitations or []),
        "success_tool_results": success,
        "critic_verdict": critic.verdict,
        "critic_issues": _structured_issues(critic),
        "log": log_text,
    }
    system_prompt = (
        _load_prompt(settings.V3_REVISION_PROMPT_PATH).rstrip()
        + "\n\n"
        + vocabulary_prompt_block()
        + "\n"
    )
    user_prompt = (
        "다음 관찰 가능한 정보와 Critic structured issue만 사용하십시오.\n"
        "planner reason, tool selection reason, Ground Truth, case_id는 없습니다.\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n"
    )
    return _parse_json_with_retry(system_prompt, user_prompt, RevisionDraft)


def _apply_post_revision(
    draft: dict,
    *,
    v2: V2DiagnosisResult,
    critic: CriticResult,
    log_text: str,
) -> dict:
    payload = dict(draft)
    payload["evidence"] = filter_evidence(payload.get("evidence") or [], v2.tool_results)
    if not payload["evidence"]:
        payload["evidence"] = [
            f"{item.tool}: {json.dumps(item.data, ensure_ascii=False)}"
            for item in supporting_tool_results(v2.tool_results)
        ]
    original_level = payload.get("diagnosis_level") or "추정"
    payload["diagnosis_level"] = apply_diagnosis_level_policy(
        original_level, v2.tool_results
    )
    owner = (payload.get("owner") or "").strip()
    if owner and v2.owner:
        payload["owner"] = v2.owner
    elif not owner:
        payload["owner"] = v2.owner or "BATCH_OPERATION"
    try:
        payload["final_cause_code"] = validate_cause_code(
            str(payload.get("final_cause_code") or "").strip()
        )
    except ValueError:
        payload["final_cause_code"] = v2.final_cause_code
        payload["final_cause_name"] = v2.final_cause_name
    if payload["final_cause_code"] != v2.final_cause_code:
        if not cause_revision_allowed(
            critic,
            current_cause=v2.final_cause_code,
            log_text=log_text,
            extracted_info=v2.extracted_info,
            tool_results=v2.tool_results,
        ):
            payload["final_cause_code"] = v2.final_cause_code
            payload["final_cause_name"] = v2.final_cause_name
    payload["final_cause_name"] = (
        payload.get("final_cause_name")
        or CAUSE_CODE_NAMES.get(payload["final_cause_code"], payload["final_cause_code"])
    )
    return payload


def _pack_v3(
    v2: V2DiagnosisResult,
    critic: CriticResult,
    *,
    summary: str,
    final_cause_code: str,
    final_cause_name: str,
    diagnosis_level: str,
    owner: str,
    evidence: list[str],
    limitations: list[str],
    recommended_actions: list[str],
) -> V3DiagnosisResult:
    revised = (
        final_cause_code != v2.final_cause_code
        or diagnosis_level != v2.diagnosis_level
    )
    return V3DiagnosisResult(
        version="v3",
        case_id=v2.case_id,
        summary=summary,
        extracted_info=v2.extracted_info,
        initial_hypotheses=v2.initial_hypotheses,
        working_hypotheses=v2.working_hypotheses,
        investigation_plan=v2.investigation_plan,
        unresolved_questions=v2.unresolved_questions,
        current_round=v2.current_round,
        stop_reason=v2.stop_reason,
        planning_trace=v2.planning_trace,
        selected_tools=v2.selected_tools,
        tool_results=v2.tool_results,
        critic_result=critic,
        revised=revised,
        original_v2_cause_code=v2.final_cause_code,
        original_v2_diagnosis_level=v2.diagnosis_level,
        original_v2_owner=v2.owner,
        final_cause_code=final_cause_code,
        final_cause_name=final_cause_name,
        diagnosis_level=diagnosis_level,  # type: ignore[arg-type]
        owner=owner,
        evidence=evidence,
        limitations=limitations,
        recommended_actions=recommended_actions,
    )


def diagnose_v3(
    log_text: str,
    case_id: str | None = None,
    *,
    v2_result: V2DiagnosisResult | None = None,
    critic_fn=None,
    revise_fn: Callable[..., RevisionDraft] | None = None,
    diagnose_v2_fn=None,
) -> V3DiagnosisResult:
    producer = diagnose_v2_fn or diagnose_v2
    if v2_result is None:
        v2 = _v2_snapshot(producer(log_text, case_id=case_id))
    else:
        v2 = _v2_snapshot(v2_result)

    critic_calls = {"n": 0}

    def _critic_once(text, result):
        if critic_calls["n"] >= MAX_CRITIC_CALLS:
            raise RuntimeError("Critic는 1회만 호출할 수 있습니다.")
        critic_calls["n"] += 1
        if critic_fn is None:
            return run_critic(text, result)
        return run_critic(text, result, critic_fn=critic_fn)

    critic = _critic_once(log_text, v2)

    if critic.verdict == "PASS":
        return _pack_v3(
            v2,
            critic,
            summary=v2.summary,
            final_cause_code=v2.final_cause_code,
            final_cause_name=v2.final_cause_name,
            diagnosis_level=v2.diagnosis_level,
            owner=v2.owner,
            evidence=list(v2.evidence),
            limitations=list(v2.limitations),
            recommended_actions=list(v2.recommended_actions),
        )

    revision_calls = {"n": 0}

    def _revise_once() -> dict:
        if revision_calls["n"] >= MAX_REVISION_CALLS:
            raise RuntimeError("Revision은 1회만 호출할 수 있습니다.")
        revision_calls["n"] += 1
        runner = revise_fn or call_revision_llm
        draft = runner(log_text, v2, critic)
        return _apply_post_revision(draft.model_dump(), v2=v2, critic=critic, log_text=log_text)

    payload = _revise_once()
    limitations = list(payload.get("limitations") or [])
    if not cause_revision_allowed(
        critic,
        current_cause=v2.final_cause_code,
        log_text=log_text,
        extracted_info=v2.extracted_info,
        tool_results=v2.tool_results,
    ) and payload["final_cause_code"] == v2.final_cause_code:
        for item in critic.issues:
            if item.issue_type.value == "FAILED_EVIDENCE_USED":
                note = "FAILED Tool error는 최종 supporting evidence에서 제외했습니다."
                if note not in limitations:
                    limitations.append(note)
    return _pack_v3(
        v2,
        critic,
        summary=payload.get("summary") or v2.summary,
        final_cause_code=payload["final_cause_code"],
        final_cause_name=payload["final_cause_name"],
        diagnosis_level=payload["diagnosis_level"],
        owner=payload["owner"],
        evidence=list(payload.get("evidence") or []),
        limitations=limitations,
        recommended_actions=list(payload.get("recommended_actions") or []),
    )
