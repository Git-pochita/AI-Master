import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.schemas import (
    DiagnosisResult,
    Hypothesis,
    ToolResult,
    ToolSelection,
    V1DiagnosisResult,
)
from main import run_diagnosis


def _hypothesis() -> Hypothesis:
    return Hypothesis(
        cause_code="INPUT_FILE_NOT_FOUND",
        cause_name="입력 파일 없음",
        evidence=["FileNotFoundError"],
    )


def test_v1_result_schema_valid():
    result = V1DiagnosisResult(
        case_id="file_case_001",
        summary="Tool 결과를 반영한 진단",
        extracted_info={"job_name": "DAILY_SALES_LOAD"},
        initial_hypotheses=[_hypothesis()],
        selected_tools=[
            ToolSelection(
                selected_tool="validate_parameter",
                reason="business_date 검증",
                arguments={
                    "job_name": "DAILY_SALES_LOAD",
                    "parameter_name": "business_date",
                    "parameter_value": "20260818",
                },
            )
        ],
        tool_results=[
            ToolResult(
                tool="validate_parameter",
                status="SUCCESS",
                data={"is_valid": False},
                error=None,
            )
        ],
        final_cause_code="INVALID_BUSINESS_DATE",
        final_cause_name="실행일자 파라미터 오류",
        diagnosis_level="확인됨",
        owner="BATCH_OPERATION",
        evidence=["validate_parameter: is_valid=false"],
        limitations=["mock 데이터 범위로만 확인함"],
    )
    dumped = result.model_dump()
    for key in [
        "initial_hypotheses",
        "selected_tools",
        "tool_results",
        "final_cause_code",
        "final_cause_name",
        "diagnosis_level",
        "owner",
        "evidence",
        "limitations",
    ]:
        assert key in dumped
    V1DiagnosisResult.model_validate(dumped)


def test_v1_schema_rejects_bad_cause_code():
    with pytest.raises(ValidationError):
        V1DiagnosisResult(
            initial_hypotheses=[_hypothesis()],
            final_cause_code="invalid-date",
            final_cause_name="오류",
            diagnosis_level="추정",
            owner="BATCH_OPERATION",
            evidence=["x"],
            limitations=["y"],
        )


def test_v0_execution_path_kept(monkeypatch):
    fake = DiagnosisResult(
        case_id="file_case_001",
        summary="V0 유지",
        extracted_info={},
        hypotheses=[_hypothesis()],
        final_cause_code="INPUT_FILE_NOT_FOUND",
        final_cause_name="입력 파일 없음",
        diagnosis_level="추정",
        owner="BATCH_OPERATION",
        recommended_actions=["확인"],
        limitations=["로그만 사용"],
    )
    monkeypatch.setattr("main.diagnose", lambda log_text, case_id=None: fake)
    result = run_diagnosis("v0", "dummy log", "file_case_001")
    assert isinstance(result, DiagnosisResult)
    dumped = result.model_dump()
    assert "selected_tools" not in dumped
    assert "tool_results" not in dumped
    assert dumped["final_cause_code"] == "INPUT_FILE_NOT_FOUND"


def test_tool_use_has_no_static_log_routing():
    source = (PROJECT_ROOT / "app" / "tool_use.py").read_text(encoding="utf-8")
    assert 'if "FileNotFoundError"' not in source
    assert "if error_code" not in source
