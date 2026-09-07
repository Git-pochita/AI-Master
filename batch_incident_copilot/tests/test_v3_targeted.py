from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.cause_codes import CAUSE_CODE_NAMES
from app.critic import CriticLLMDraft
from app.schemas import (
    CriticIssue,
    CriticIssueType,
    Hypothesis,
    StopReason,
    ToolResult,
    V2DiagnosisResult,
)
from app.v3 import RevisionDraft, diagnose_v3


def _v2_result(
    cause_code: str,
    *,
    tool_results: list[ToolResult],
    diagnosis_level: str = "확인됨",
    evidence: list[str] | None = None,
) -> V2DiagnosisResult:
    return V2DiagnosisResult(
        case_id="targeted-v3",
        initial_hypotheses=[
            Hypothesis(
                cause_code=cause_code,
                cause_name=CAUSE_CODE_NAMES[cause_code],
                evidence=["입력 로그"],
            )
        ],
        stop_reason=StopReason.EVIDENCE_SUFFICIENT,
        tool_results=tool_results,
        final_cause_code=cause_code,
        final_cause_name=CAUSE_CODE_NAMES[cause_code],
        diagnosis_level=diagnosis_level,
        owner="BATCH_OPERATION",
        evidence=list(evidence or []),
        limitations=[],
        recommended_actions=[],
    )


def _issue(issue_type: CriticIssueType, token: str) -> CriticIssue:
    return CriticIssue(
        issue_type=issue_type,
        description=issue_type.value,
        related_evidence=[token],
        blocking=True,
    )


def _revision(v2: V2DiagnosisResult, cause_code: str) -> RevisionDraft:
    return RevisionDraft(
        summary="관찰 가능한 SUCCESS Tool 근거로 진단을 재검토했습니다.",
        final_cause_code=cause_code,
        final_cause_name=CAUSE_CODE_NAMES[cause_code],
        diagnosis_level=v2.diagnosis_level,
        owner=v2.owner,
        evidence=list(v2.evidence),
        limitations=[],
        recommended_actions=[],
    )


def _run(
    log_text: str,
    v2: V2DiagnosisResult,
    *,
    critic_fn,
    revise_fn,
):
    return diagnose_v3(
        log_text,
        v2_result=v2,
        critic_fn=critic_fn,
        revise_fn=revise_fn,
        diagnose_v2_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("주입한 v2_result가 있으면 diagnose_v2를 호출하면 안 됩니다.")
        ),
    )


def test_critic_corrects_v2_cause_when_success_evidence_supports_alternative():
    observed_file = "sales_20260901.csv"
    v2 = _v2_result(
        "FILE_NOT_RECEIVED",
        tool_results=[
            ToolResult(
                tool="check_file_status",
                status="SUCCESS",
                data={
                    "path": "/data/in/sale_20260901.csv",
                    "exists": False,
                    "received": False,
                    "same_directory_files": [
                        {
                            "path": f"/data/in/{observed_file}",
                            "exists": True,
                            "received": True,
                        }
                    ],
                },
            )
        ],
        evidence=[f"동일 경로에서 {observed_file} 수신 확인"],
    )

    def critic_fn(*_args, **_kwargs):
        return CriticLLMDraft(
            evidence_consistent=False,
            issues=[
                _issue(CriticIssueType.EVIDENCE_CONFLICT, observed_file),
                _issue(CriticIssueType.BETTER_SUPPORTED_CAUSE, observed_file),
            ],
            recommended_cause_code="INVALID_FILE_PATH",
        )

    result = _run(
        "FileNotFoundError: /data/in/sale_20260901.csv",
        v2,
        critic_fn=critic_fn,
        revise_fn=lambda _log, producer, _critic: _revision(
            producer, "INVALID_FILE_PATH"
        ),
    )

    assert result.final_cause_code == "INVALID_FILE_PATH"
    assert result.original_v2_cause_code == "FILE_NOT_RECEIVED"
    assert result.revised is True


def test_critic_protects_supported_v2_cause_without_both_revision_conditions():
    evidence_token = "parameter_value=20260931"
    v2 = _v2_result(
        "INVALID_BUSINESS_DATE",
        tool_results=[
            ToolResult(
                tool="validate_parameter",
                status="SUCCESS",
                data={
                    "parameter_name": "business_date",
                    "parameter_value": "20260931",
                    "expected_value": "20260930",
                    "is_valid": False,
                },
            )
        ],
        evidence=[evidence_token, "is_valid=false"],
    )

    def critic_fn(*_args, **_kwargs):
        return CriticLLMDraft(
            evidence_consistent=False,
            issues=[_issue(CriticIssueType.EVIDENCE_CONFLICT, evidence_token)],
            recommended_cause_code="INVALID_PARAMETER_FORMAT",
        )

    result = _run(
        "business_date validation failed: 20260931",
        v2,
        critic_fn=critic_fn,
        revise_fn=lambda _log, producer, _critic: _revision(
            producer, "INVALID_PARAMETER_FORMAT"
        ),
    )

    assert result.final_cause_code == "INVALID_BUSINESS_DATE"
    assert result.original_v2_cause_code == "INVALID_BUSINESS_DATE"
    assert result.revised is False


def test_confirmed_level_is_capped_and_failed_tool_is_not_supporting_evidence():
    failed_error = "parameter service unavailable"
    v2 = _v2_result(
        "INVALID_BUSINESS_DATE",
        tool_results=[
            ToolResult(
                tool="validate_parameter",
                status="FAILED",
                data=None,
                error=failed_error,
            )
        ],
        evidence=[failed_error],
    )

    result = _run(
        "business_date validation failed",
        v2,
        critic_fn=lambda *_args, **_kwargs: CriticLLMDraft(),
        revise_fn=lambda _log, producer, _critic: _revision(
            producer, producer.final_cause_code
        ),
    )

    assert result.diagnosis_level == "추정"
    assert failed_error not in result.evidence
    assert result.evidence == []
    assert result.revised is True
