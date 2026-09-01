# Batch Incident Copilot — V1 고정 상태와 V2 다음 단계

이 문서는 2026-09-01 작업 상태를 고정한 handoff입니다. V2/V3는 아직 구현하지 않습니다.

이어갈 브랜치: `cursor/eval-30-case-gt-32d6`  
현재 작업 PR: https://github.com/Git-pochita/AI-Master/pull/7 (draft, merge 금지)  
공식 평가 리포트: `evaluation/reports/v0_vs_v1.md`

## 확정 상태

- V0 / V1 구현 완료
- Streamlit Agent Execution Trace 구현 완료
- File / Parameter / DB / SQL Tool 구현 완료 (로컬 mock JSON만 조회)
- Canonical Cause Code unique **12개** (`app/cause_codes.py`). `INVALID_BUSINESS_DATE`는 FILE·PARAMETER 그룹에 중복 등록됨
- evaluator / Batch Runner 구현 완료
- 공식 Ground Truth **30건** 구축 완료 (`evaluation/ground_truth.json`, 로그 `data/sample_logs/{F,P,D,S,C}-NN.log`)
- Azure OpenAI `gpt-4.1` 기준 V0/V1 공식 30건 평가 완료
- 실행 실패 0건 (`failed_runs=0`)
- pytest 89 passed (handoff 시점 재실행 결과는 commit/PR에 기록)

## 공식 30건 평가 결과 (baseline, 고정)

출처: `evaluation/reports/v0_summary.json`, `evaluation/reports/v1_summary.json`, `evaluation/reports/v0_vs_v1.md`

| Metric | V0 | V1 |
| --- | --- | --- |
| Final Diagnosis Accuracy | 73.3% (22/30) | 93.3% (28/30) |
| Hypothesis Recall | 86.7% | 86.7% |
| Diagnosis Level Accuracy | 93.3% | 100.0% |
| Owner Accuracy | 100.0% | 100.0% |
| Required Tool Recall | N/A | 95.0% |
| Unnecessary Tool Rate | N/A | 6.7% |
| 평균 실행시간 | 6.17초/건 | 14.57초/건 |

위 실행시간은 로컬 PoC latency이며 운영 장애 분석 시간 절감 수치가 아닙니다.

이 숫자는 V1 baseline입니다. Agent/Prompt/평가 결과를 케이스에 맞춰 추가 튜닝하지 마십시오.

## V1 주요 실패

### F-05 — Planning / 추가 조사 / Re-planning

- GT: `INVALID_BUSINESS_DATE`
- Prediction: `FILE_NOT_RECEIVED`
- `check_file_status`만 호출, `validate_parameter` 미호출
- Required Tool Recall 0.5

### F-04 — Evidence interpretation / Critic

- GT: `INVALID_FILE_PATH`
- Prediction: `FILE_NOT_RECEIVED`
- 필요한 `check_file_status`는 정상 호출 (Tool Recall 1.0)
- 최종 Cause 해석 실패

## 기타 관찰

- P-05, C-01: `tool_necessity=NOT_NEEDED`인데 Tool 호출 발생. 호출 필요 여부/종료 조건 개선 필요
- D-05, C-05: `NOT_CALLABLE`. 필수 인자/근거 부족으로 호출하지 않음
- FAILED Tool 결과는 final evidence에서 제외하는 기존 정책 유지

GT metadata `tool_necessity` (`REQUIRED` / `NOT_NEEDED` / `NOT_CALLABLE`)는 해석용입니다. Tool Recall / Unnecessary Tool Rate 채점 공식은 바꾸지 않았습니다.

## 다음 개발 순서

1. V2 Dynamic Planning / Re-planning 설계
2. V2 구현
3. 동일 30건으로 V1 vs V2 평가
4. 실패 분석
5. V3 Critic / Reflection 설계 및 구현

## V2 최소 목표 (미구현)

- 현재 가설 상태 유지
- 조사 계획 생성
- 다음 Tool 선택
- Tool 결과를 evidence에 반영
- 현재 evidence가 충분한지 판단
- 부족하면 추가 Tool을 선택하여 Re-plan
- 충분하면 종료
- 최대 planning/tool round 제한으로 무한 루프 방지

V2/V3 LangGraph, Multi-Agent, RAG는 이 문서의 범위가 아닙니다. 구현은 다음 세션에서 합니다.

## 내일 세션 시작 방법

```bash
git checkout cursor/eval-30-case-gt-32d6
git pull origin cursor/eval-30-case-gt-32d6
cd batch_incident_copilot
cp .env.example .env   # API Key는 git에 없음. 로컬/Secrets로만 설정
python -m pytest -q
```

재평가(필요 시):

```bash
cd batch_incident_copilot
python evaluation/run_evaluation.py --versions v0 v1
```

`.env`와 API Key는 커밋하지 않습니다.
