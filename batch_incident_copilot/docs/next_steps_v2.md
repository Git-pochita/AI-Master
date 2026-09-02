# Batch Incident Copilot — V2 완료 상태와 V3 다음 단계

이 문서는 V0/V1/V2가 `main`에 반영된 이후의 handoff입니다. 기존 평가 리포트는 덮어쓰지 않습니다.

기준 브랜치: `main`  
V2 설계: [`v2_dynamic_planning_design.md`](v2_dynamic_planning_design.md)  
V0/V1 공식 리포트: `evaluation/reports/v0_vs_v1.md`  
V2 1차 리포트: `evaluation/reports/v1_vs_v2.md`  
V2 refined 리포트: `evaluation/reports/v1_vs_v2_refined.md`

## 확정 상태

- V0 Baseline 완료
- V1 Function Tool Use 완료
- Streamlit Agent Execution Trace 완료 (V0/V1/V2)
- File / Parameter / DB / SQL Tool 완료 (로컬 mock JSON만 조회)
- Canonical Cause Code unique **12개** (`app/cause_codes.py`)
- 공식 Ground Truth **30건** 고정 (`evaluation/ground_truth.json`)
- V2 Dynamic Planning / Re-planning 완료 (`app/planning.py`, `diagnose_v2()`, `--version v2`)
- V2 1차 공식 30건 평가 완료 (`v2_summary.json`, `v1_vs_v2.md`) — 보존
- V2 refined 평가 완료 (`v2_refined_summary.json`, `v1_vs_v2_refined.md`)
- failed_runs = 0 (V0/V1/V2 1차/V2 refined)
- pytest 108 passed (V2 refined merge 시점)

## 공식 30건 평가 결과

출처:

- V0/V1: `evaluation/reports/v0_summary.json`, `v1_summary.json`, `v0_vs_v1.md`
- V2 1차: `evaluation/reports/v2_summary.json`, `v1_vs_v2.md`
- V2 refined: `evaluation/reports/v2_refined_summary.json`, `v1_vs_v2_refined.md`

모델: Azure OpenAI `gpt-4.1`

| Metric | V0 | V1 | V2 1차 | V2 refined |
| --- | --- | --- | --- | --- |
| Final Diagnosis Accuracy | 73.3% (22/30) | 93.3% (28/30) | 93.3% (28/30) | 93.3% (28/30) |
| Hypothesis Recall | 86.7% | 86.7% | 86.7% | 86.7% |
| Diagnosis Level Accuracy | 93.3% | 100.0% | 100.0% | 100.0% |
| Owner Accuracy | 100.0% | 100.0% | 100.0% | 100.0% |
| Required Tool Recall | N/A | 95.0% | 98.3% | 98.3% |
| Unnecessary Tool Rate | N/A | 6.7% | 15.0% | 6.7% |
| failed_runs | 0 | 0 | 0 | 0 |
| 평균 실행시간 | 6.17초/건 | 14.57초/건 | 18.478초/건 | 17.456초/건 |

실행시간은 로컬 PoC latency이며 운영 장애 분석 시간 절감 수치가 아닙니다.

Hypothesis Recall은 `initial_hypotheses` 기준이며 V2 Planning KPI가 아닙니다.

V2 1차 리포트는 raw 결과로 보존합니다. F-05 개선과 FILE 과조사(Unnecessary 15.0%), F-02 regression이 이 리포트에 남아 있습니다. 이후 코드/Prompt를 그 숫자에 맞춰 되돌려 쓰지 마십시오.

## V2 최종 지표 (refined)

현재 `main`의 V2 코드 기준:

- Final Diagnosis Accuracy **93.3%**
- Required Tool Recall **98.3%**
- Unnecessary Tool Rate **6.7%**
- F-05 개선: V1 `FILE_NOT_RECEIVED` → V2 `INVALID_BUSINESS_DATE`, `check_file_status` → `validate_parameter`
- F-02 / F-04: evidence interpretation 문제. **V3 Critic / Reflection 후보**. V2에서 고치지 않음
- failed_runs = 0

V2 1차에서 FILE 케이스에 붙었던 불필요 `validate_parameter`는 refined에서 제거했습니다 (F-01/F-03/F-04/F-06). F-05와 일자 불일치 signal이 있는 C-02/C-06의 Re-plan은 유지했습니다.

## 다음 개발 순서

1. V2 Dynamic Planning / Re-planning 설계 — 완료
2. V2 구현 — 완료 (PR #10)
3. V2 1차 30건 평가 — 완료, 리포트 보존 (PR #11)
4. V2 refined (concrete-signal 추가 조사 가드) — 완료 (PR #12)
5. **다음 작업: V3 Critic / Reflection 설계** — 미착수

V3에서 다룰 후보:

- F-02, F-04: `check_file_status` SUCCESS의 `same_directory_files` 등 FILE evidence 해석
- 최종 진단 자기검증 / Critic. V2 Planner에 case_id 분기나 F-04 special rule을 넣지 말 것

V3 LangGraph, Multi-Agent, RAG는 이 문서의 범위가 아닙니다.

## 하지 말 것

- 기존 `v0_summary.json`, `v1_summary.json`, `v0_vs_v1.md` 재실행/덮어쓰기
- 1차 `v2_summary.json`, `v1_vs_v2.md` 삭제 또는 덮어쓰기
- GT 수정, V0/V1 prompt 케이스 튜닝
- F-02/F-04를 V2에서 맞추기 위한 Critic 구현 (그것은 V3)

`.env`와 API Key는 커밋하지 않습니다.
