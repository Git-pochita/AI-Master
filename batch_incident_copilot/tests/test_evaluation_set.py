from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.cause_codes import CANONICAL_CAUSE_CODES
from app.tools.registry import HANDLERS, execute_tool
from config import settings
from evaluation.evaluator import load_ground_truth

REQUIRED_FIELDS = {
    "case_id",
    "incident_domain",
    "scenario",
    "log_file",
    "actual_cause_code",
    "expected_hypothesis_codes",
    "required_tools",
    "unnecessary_tools",
    "expected_tool_outcome",
    "expected_diagnosis_level_v0",
    "expected_diagnosis_level_v1",
    "expected_owner",
    "tool_fixtures",
}

EXPECTED_CASES = [
    "F-01",
    "F-02",
    "F-03",
    "F-04",
    "F-05",
    "F-06",
    "P-01",
    "P-02",
    "P-03",
    "P-04",
    "P-05",
    "P-06",
    "D-01",
    "D-02",
    "D-03",
    "D-04",
    "D-05",
    "D-06",
    "S-01",
    "S-02",
    "S-03",
    "S-04",
    "S-05",
    "S-06",
    "C-01",
    "C-02",
    "C-03",
    "C-04",
    "C-05",
    "C-06",
]


def test_ground_truth_has_thirty_unique_cases():
    all_gt = load_ground_truth()
    assert len(all_gt) == 30
    assert list(all_gt) == EXPECTED_CASES
    assert len(set(all_gt)) == 30


def test_ground_truth_fields_codes_tools_and_logs():
    all_gt = load_ground_truth()
    domains = {}
    causes = set()
    for case_id, gt in all_gt.items():
        assert REQUIRED_FIELDS.issubset(gt), case_id
        assert gt["case_id"] == case_id
        assert gt["log_file"] == f"{case_id}.log"
        assert gt["actual_cause_code"] in CANONICAL_CAUSE_CODES
        assert gt["actual_cause_code"] in gt["expected_hypothesis_codes"]
        causes.add(gt["actual_cause_code"])
        for code in gt["expected_hypothesis_codes"]:
            assert code in CANONICAL_CAUSE_CODES
        for tool in gt["required_tools"]:
            assert tool in HANDLERS
        for tool in gt["unnecessary_tools"]:
            assert tool in HANDLERS
        assert gt["expected_diagnosis_level_v0"] == "추정"
        assert gt["expected_diagnosis_level_v1"] in {"추정", "가능성 높음", "확인됨"}
        assert gt["expected_owner"] == "BATCH_OPERATION"
        log_path = settings.SAMPLE_LOGS_DIR / gt["log_file"]
        assert log_path.is_file(), log_path
        domains[gt["incident_domain"]] = domains.get(gt["incident_domain"], 0) + 1
    assert domains == {
        "FILE": 6,
        "PARAMETER": 6,
        "DB": 6,
        "SQL": 6,
        "COMPOSITE": 6,
    }
    assert causes == set(CANONICAL_CAUSE_CODES)


def test_tool_outcome_matches_diagnosis_level_policy():
    all_gt = load_ground_truth()
    for case_id, gt in all_gt.items():
        outcome = gt["expected_tool_outcome"]
        assert outcome in {"SUCCESS", "FAILED", "NONE", "MIXED"}, case_id
        fixtures = gt["tool_fixtures"]
        if outcome == "NONE":
            assert gt["required_tools"] == []
            assert fixtures == []
            assert gt["expected_diagnosis_level_v1"] == "추정"
        elif outcome == "FAILED":
            assert gt["required_tools"]
            assert fixtures
            assert all(item["expected_status"] == "FAILED" for item in fixtures)
            assert gt["expected_diagnosis_level_v1"] == "추정"
        elif outcome == "SUCCESS":
            assert gt["required_tools"]
            assert fixtures
            assert all(item["expected_status"] == "SUCCESS" for item in fixtures)
            assert gt["expected_diagnosis_level_v1"] == "확인됨"
        elif outcome == "MIXED":
            statuses = {item["expected_status"] for item in fixtures}
            assert statuses == {"SUCCESS", "FAILED"}
            assert gt["expected_diagnosis_level_v1"] == "확인됨"


def test_tool_fixtures_reproduce_mock_results():
    all_gt = load_ground_truth()
    for case_id, gt in all_gt.items():
        for fixture in gt["tool_fixtures"]:
            result = execute_tool(fixture["tool"], fixture.get("arguments") or {})
            assert result.status == fixture["expected_status"], (
                case_id,
                fixture["tool"],
                result.status,
                result.error,
            )
            if fixture["expected_status"] != "SUCCESS":
                assert result.data is None
                continue
            expected_data = fixture.get("expected_data") or {}
            assert result.data is not None
            for key, value in expected_data.items():
                assert result.data.get(key) == value, (case_id, fixture["tool"], key)


def test_file_and_parameter_root_causes_are_distinct():
    all_gt = load_ground_truth()
    assert all_gt["F-01"]["actual_cause_code"] == "FILE_NOT_RECEIVED"
    assert all_gt["F-02"]["actual_cause_code"] == "INVALID_FILE_PATH"
    assert all_gt["F-05"]["actual_cause_code"] == "INVALID_BUSINESS_DATE"
    assert all_gt["F-05"]["required_tools"] == ["check_file_status", "validate_parameter"]
    assert all_gt["P-05"]["required_tools"] == []
    assert all_gt["C-06"]["expected_tool_outcome"] == "MIXED"
