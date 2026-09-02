# V2 refined vs V3 Official Evaluation

## 평가 조건

- Ground Truth 30건 동일. GT / V3 prompt / V2 planner 미수정
- V2 refined: 공식 `v2_refined_summary.json` / `v1_vs_v2_refined.md` (이 평가에서 덮어쓰지 않음)
- V3: freeze된 `diagnose_v3()`를 `run_evaluation.py --versions v3`로 **한 번** 실행
- 기준 main SHA: `93704782f1dc03035e7c2e59db50577572618def`
- 모델: Azure OpenAI `gpt-4.1`
- endpoint: `https://skax.ai-talentlab.com` / API version `2024-12-01-preview`
- raw 결과: `results/v3_critic/<case_id>.json`
- summary: `evaluation/reports/v3_summary.json`
- 이 평가에서 implementation / prompt tuning / 재실행 없음

## 비교표

Metric | V2 refined | V3
--- | --- | ---
Final Diagnosis Accuracy | 93.3% (28/30) | 93.3% (28/30)
Hypothesis Recall | 86.7% | 83.3%
Diagnosis Level Accuracy | 100.0% | 100.0%
Owner Accuracy | 100.0% | 100.0%
Required Tool Recall | 98.3% | 96.7%
Unnecessary Tool Rate | 6.7% | 6.7%
failed_runs | 0 | 0
평균 실행시간 | 17.456초/건 | 20.201초/건
average tool calls | 1.067 | 1.033
tool failure count | 5 | 5
Critic Revision Count | n/a | 1
Critic Revision Precision | n/a | 0.0
Unnecessary Revision Rate | n/a | 0.0
Net Corrected Cases | n/a | 0
Regression Cases | n/a | 0

Hypothesis Recall / Required Tool Recall 차이는 Critic이 아니라 **이번 live V2 Producer 재실행**의 조사 결과 차이입니다.

- D-04: V2 refined initial hypotheses에 `DB_ACCOUNT_LOCKED`가 있었으나 이번 live V2에는 `DB_CREDENTIAL_MISMATCH`만 있어 recall miss 1건 증가
- C-03: V2 refined는 `check_sql_metadata, check_db_status` (recall 1.0), 이번 live V2는 `check_sql_metadata`만 (recall 0.5)

live V2 `original_v2_cause_code`는 30건 모두 공식 V2 refined final cause와 같았습니다.

## V3 전용 KPI

- Critic Revision Count = 1 (`F-05`만 `verdict=REVISE`)
- Critic Revision Precision = 0 / 1 = 0.0  
  REVISE 1건은 이미 정답이던 V2(`INVALID_BUSINESS_DATE`)를 교정하지 못했고, Cause Revision Gate가 cause 변경을 막음 (`revised=false`)
- Unnecessary Revision Rate = 0.0  
  V2가 정답이던 28건에서 V3가 cause를 바꿔 오답으로 만든 건수 = 0
- Net Corrected = 0 (`F-02`, `F-04` 미교정)
- Regression = 0

## F-02 / F-04

case_id | expected | V2 final | Critic verdict | issue types | recommended | Gate | revised | V3 final | correct
--- | --- | --- | --- | --- | --- | --- | --- | --- | ---
F-02 | INVALID_FILE_PATH | FILE_NOT_RECEIVED | PASS | [] | null | False | false | FILE_NOT_RECEIVED | incorrect
F-04 | INVALID_FILE_PATH | FILE_NOT_RECEIVED | PASS | [] | null | False | false | FILE_NOT_RECEIVED | incorrect

`FILE_NOT_RECEIVED → INVALID_FILE_PATH` 교정은 두 건 모두 일어나지 않았습니다. Critic이 PASS를 반환해 Revision에 들어가지 않았습니다.

## V2 정답 28건 보호

공식 V2 refined가 정답이던 28건은 V3도 모두 정답입니다. regression 목록은 비어 있습니다.

case_id | V2 | critic | revised | V3 | regression
--- | --- | --- | --- | --- | ---
F-01 | FILE_NOT_RECEIVED | PASS | false | FILE_NOT_RECEIVED | no
F-03 | FILE_NOT_RECEIVED | PASS | false | FILE_NOT_RECEIVED | no
F-05 | INVALID_BUSINESS_DATE | REVISE | false | INVALID_BUSINESS_DATE | no
F-06 | FILE_NOT_RECEIVED | PASS | false | FILE_NOT_RECEIVED | no
P-01 | INVALID_BUSINESS_DATE | PASS | false | INVALID_BUSINESS_DATE | no
P-02 | MISSING_REQUIRED_PARAMETER | PASS | false | MISSING_REQUIRED_PARAMETER | no
P-03 | INVALID_PARAMETER_FORMAT | PASS | false | INVALID_PARAMETER_FORMAT | no
P-04 | INVALID_PARAMETER_RANGE | PASS | false | INVALID_PARAMETER_RANGE | no
P-05 | INVALID_BUSINESS_DATE | PASS | false | INVALID_BUSINESS_DATE | no
P-06 | INVALID_PARAMETER_FORMAT | PASS | false | INVALID_PARAMETER_FORMAT | no
D-01 | DB_CREDENTIAL_MISMATCH | PASS | false | DB_CREDENTIAL_MISMATCH | no
D-02 | DB_ACCOUNT_LOCKED | PASS | false | DB_ACCOUNT_LOCKED | no
D-03 | DB_CONNECTION_CONFIG_ERROR | PASS | false | DB_CONNECTION_CONFIG_ERROR | no
D-04 | DB_ACCOUNT_LOCKED | PASS | false | DB_ACCOUNT_LOCKED | no
D-05 | DB_CREDENTIAL_MISMATCH | PASS | false | DB_CREDENTIAL_MISMATCH | no
D-06 | DB_CONNECTION_CONFIG_ERROR | PASS | false | DB_CONNECTION_CONFIG_ERROR | no
S-01 | TABLE_NOT_FOUND | PASS | false | TABLE_NOT_FOUND | no
S-02 | COLUMN_NOT_FOUND | PASS | false | COLUMN_NOT_FOUND | no
S-03 | INVALID_SCHEMA | PASS | false | INVALID_SCHEMA | no
S-04 | TABLE_NOT_FOUND | PASS | false | TABLE_NOT_FOUND | no
S-05 | COLUMN_NOT_FOUND | PASS | false | COLUMN_NOT_FOUND | no
S-06 | INVALID_SCHEMA | PASS | false | INVALID_SCHEMA | no
C-01 | DB_ACCOUNT_LOCKED | PASS | false | DB_ACCOUNT_LOCKED | no
C-02 | INVALID_BUSINESS_DATE | PASS | false | INVALID_BUSINESS_DATE | no
C-03 | TABLE_NOT_FOUND | PASS | false | TABLE_NOT_FOUND | no
C-04 | TABLE_NOT_FOUND | PASS | false | TABLE_NOT_FOUND | no
C-05 | FILE_NOT_RECEIVED | PASS | false | FILE_NOT_RECEIVED | no
C-06 | INVALID_BUSINESS_DATE | PASS | false | INVALID_BUSINESS_DATE | no

F-05는 Critic이 `FILE_NOT_RECEIVED`를 권고했으나 related_evidence 문자열이 observable payload에서 확인되지 않아 Gate=False, 최종 cause는 V2를 유지했습니다.

## Critic behavior

category | count | cases
--- | --- | ---
PASS + V2 correct | 27 | F-02/F-04/F-05 제외 나머지
PASS + V2 wrong | 2 | F-02, F-04
REVISE + corrected | 0 | -
REVISE + unchanged | 1 | F-05
REVISE + regression | 0 | -
REVISE + still wrong | 0 | -

## FAILED evidence

FAILED Tool이 있는 케이스: F-06, P-06, D-06, S-06, C-06

- FAILED error가 final evidence에 포함된 건수: **0**
- SUCCESS 없이 `확인됨`인 건수: **0** (C-06은 FAILED file + SUCCESS `validate_parameter`로 `확인됨` 유지, GT와 일치)
- Critic이 이들 케이스에서 cause를 바꾼 건수: **0**

`FAILED evidence misuse = 0`

## 해석

이상적 목표(30/30, Net corrected 2)에는 도달하지 못했습니다. 최소 성공 후보(Accuracy >= 96.7% and Regression = 0) 중 Accuracy는 93.3%로 미달, Regression은 0입니다.

이 문서는 raw 결과 고정용입니다. 재평가나 추가 튜닝을 하지 않았습니다.
