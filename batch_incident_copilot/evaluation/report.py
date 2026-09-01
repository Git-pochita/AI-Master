from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def _pct(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.1f}%"


def _na(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return _pct(value)
    return str(value)


def domain_counts(ground_truth: dict) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in ground_truth.values():
        counts[str(item.get("incident_domain") or "UNKNOWN")] += 1
    return dict(sorted(counts.items()))


def tool_necessity_counts(ground_truth: dict) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in ground_truth.values():
        counts[str(item.get("tool_necessity") or "UNKNOWN")] += 1
    return dict(sorted(counts.items()))


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def render_comparison_markdown(
    *,
    v0: dict[str, Any] | None,
    v1: dict[str, Any] | None,
    ground_truth: dict,
    model: str,
    notes: list[str],
) -> str:
    counts = domain_counts(ground_truth)
    necessity = tool_necessity_counts(ground_truth)
    total = len(ground_truth)
    domain_lines = ", ".join(f"{name} {n}건" for name, n in counts.items()) or "없음"
    necessity_lines = ", ".join(f"{name} {n}건" for name, n in necessity.items()) or "없음"
    lines = [
        "# V0 vs V1 Evaluation",
        "",
        "## 평가 조건",
        "",
        f"- 총 평가 케이스: {total}",
        f"- 장애 영역별 건수: {domain_lines}",
        f"- Tool 호출 기대(GT metadata): {necessity_lines}",
        "- Tool 호출 기대 구분: REQUIRED=원인 검증에 Tool 필요, NOT_NEEDED=로그 근거가 충분하여 Tool 불필요, NOT_CALLABLE=필수 인자/근거 부족으로 호출 불가",
        "- Tool Recall / Unnecessary Tool Rate 채점 공식은 변경하지 않았습니다. 위 구분은 해석용 metadata입니다.",
        f"- 사용 모델: `{model}`",
        "- 실행 환경: local/mock PoC. Tool은 로컬 JSON만 조회하며 실제 운영 DB/파일시스템에 접속하지 않습니다.",
        "- execution time이 있어도 로컬 PoC 측정값이며, 운영 장애 분석 시간 절감을 의미하지 않습니다.",
    ]
    for note in notes:
        lines.append(f"- {note}")
    lines.extend(
        [
            "",
            "## 비교표",
            "",
            "Metric | V0 | V1",
            "--- | --- | ---",
            f"Final Diagnosis Accuracy | {_na((v0 or {}).get('final_diagnosis_accuracy'))} | {_na((v1 or {}).get('final_diagnosis_accuracy'))}",
            f"Hypothesis Recall | {_na((v0 or {}).get('hypothesis_recall'))} | {_na((v1 or {}).get('hypothesis_recall'))}",
            f"Diagnosis Level Accuracy | {_na((v0 or {}).get('diagnosis_level_accuracy'))} | {_na((v1 or {}).get('diagnosis_level_accuracy'))}",
            f"Owner Accuracy | {_na((v0 or {}).get('owner_accuracy'))} | {_na((v1 or {}).get('owner_accuracy'))}",
            f"Required Tool Recall | N/A | {_na((v1 or {}).get('required_tool_recall'))}",
            f"Unnecessary Tool Rate | N/A | {_na((v1 or {}).get('unnecessary_tool_rate'))}",
            "",
            "## 케이스별 결과",
            "",
            "case_id | actual cause | V0 final cause | V1 final cause | V1 selected tools | V0 | V1",
            "--- | --- | --- | --- | --- | --- | ---",
        ]
    )
    v0_cases = {row.get("case_id"): row for row in (v0 or {}).get("cases") or []}
    v1_cases = {row.get("case_id"): row for row in (v1 or {}).get("cases") or []}
    for case_id, gt in ground_truth.items():
        left = v0_cases.get(case_id) or {}
        right = v1_cases.get(case_id) or {}
        tools = ", ".join(right.get("selected_tools") or []) or "-"
        v0_cause = left.get("predicted_final_cause_code") or left.get("error") or "-"
        v1_cause = right.get("predicted_final_cause_code") or right.get("error") or "-"
        v0_ok = "correct" if left.get("final_diagnosis_correct") else "incorrect"
        v1_ok = "correct" if right.get("final_diagnosis_correct") else "incorrect"
        if left.get("run_status") == "failed":
            v0_ok = "failed"
        if right.get("run_status") == "failed":
            v1_ok = "failed"
        lines.append(
            f"{case_id} | {gt.get('actual_cause_code')} | {v0_cause} | {v1_cause} | {tools} | {v0_ok} | {v1_ok}"
        )
    lines.append("")
    return "\n".join(lines)
