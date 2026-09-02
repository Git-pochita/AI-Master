# V1 vs V2 Evaluation

## 평가 조건

- 총 평가 케이스: 30
- Ground Truth: `evaluation/ground_truth.json` 공식 30건 (PR #7). 이 평가에서 GT를 수정하지 않음
- 장애 영역별 건수: COMPOSITE 6건, DB 6건, FILE 6건, PARAMETER 6건, SQL 6건
- Tool 호출 기대(GT metadata): NOT_CALLABLE 2건, NOT_NEEDED 2건, REQUIRED 26건
- V1 비교 기준: 기존 공식 `evaluation/reports/v1_summary.json` / `v0_vs_v1.md`. V1을 재실행하지 않음
- V2 실행: `python3 evaluation/run_evaluation.py --versions v2`
- 모델: Azure OpenAI `gpt-4.1`
- 실행 환경: local/mock PoC. Tool은 로컬 JSON만 조회
- 기존 공식 `v0_summary.json`, `v1_summary.json`, `v0_vs_v1.md`는 runner가 덮어쓰지 않음 (sha256 확인)
- Agent / Prompt / GT는 평가 전후에 수정하지 않음
- Hypothesis Recall은 `initial_hypotheses` 기준이며 V2 Dynamic Planning KPI가 아님
- execution time은 로컬 PoC 측정값이며 운영 장애 분석 시간 절감을 의미하지 않음
- V2 summary의 Tool 집계 필드(`required_tool_recall` 등)는 `evaluation/metrics.py`의 v1 집계 공식을 cases[]에 동일 적용해 추가. 케이스별 채점은 runner 원본

## 비교표

Metric | V1 (공식 baseline) | V2 (이번 실행)
--- | --- | ---
Final Diagnosis Accuracy | 93.3% (28/30) | 93.3% (28/30)
Hypothesis Recall | 86.7% | 86.7%
Diagnosis Level Accuracy | 100.0% | 100.0%
Owner Accuracy | 100.0% | 100.0%
Required Tool Recall | 95.0% | 98.3%
Unnecessary Tool Rate | 6.7% | 15.0%
failed_runs | 0 | 0
평균 실행시간 | 14.57초/건 | 18.478초/건
average_tool_calls | 1.033 | 1.233
tool_failure_count | 4 | 6

## 케이스별 결과

case_id | actual cause | V1 final | V2 final | V1 | V2 | V1 tools | V2 tools | V2 tool recall | V2 unnecessary | V2 stop_reason
--- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---
F-01 | FILE_NOT_RECEIVED | FILE_NOT_RECEIVED | FILE_NOT_RECEIVED | correct | correct | check_file_status | check_file_status, validate_parameter | 1.0 | yes (1) | EVIDENCE_SUFFICIENT
F-02 | INVALID_FILE_PATH | INVALID_FILE_PATH | FILE_NOT_RECEIVED | correct | incorrect | check_file_status | check_file_status, validate_parameter | 1.0 | yes (1) | NO_ACTIONABLE_TOOL
F-03 | FILE_NOT_RECEIVED | FILE_NOT_RECEIVED | FILE_NOT_RECEIVED | correct | correct | check_file_status | check_file_status, validate_parameter | 1.0 | yes (1) | NO_ACTIONABLE_TOOL
F-04 | INVALID_FILE_PATH | FILE_NOT_RECEIVED | FILE_NOT_RECEIVED | incorrect | incorrect | check_file_status | check_file_status, validate_parameter | 1.0 | yes (1) | EVIDENCE_SUFFICIENT
F-05 | INVALID_BUSINESS_DATE | FILE_NOT_RECEIVED | INVALID_BUSINESS_DATE | incorrect | correct | check_file_status | check_file_status, validate_parameter | 1.0 | no (0) | EVIDENCE_SUFFICIENT
F-06 | FILE_NOT_RECEIVED | FILE_NOT_RECEIVED | FILE_NOT_RECEIVED | correct | correct | check_file_status | check_file_status, validate_parameter | 1.0 | yes (1) | NO_ACTIONABLE_TOOL
P-01 | INVALID_BUSINESS_DATE | INVALID_BUSINESS_DATE | INVALID_BUSINESS_DATE | correct | correct | validate_parameter | validate_parameter | 1.0 | no (0) | EVIDENCE_SUFFICIENT
P-02 | MISSING_REQUIRED_PARAMETER | MISSING_REQUIRED_PARAMETER | MISSING_REQUIRED_PARAMETER | correct | correct | validate_parameter | validate_parameter | 1.0 | no (0) | EVIDENCE_SUFFICIENT
P-03 | INVALID_PARAMETER_FORMAT | INVALID_PARAMETER_FORMAT | INVALID_PARAMETER_FORMAT | correct | correct | validate_parameter | validate_parameter | 1.0 | no (0) | EVIDENCE_SUFFICIENT
P-04 | INVALID_PARAMETER_RANGE | INVALID_PARAMETER_RANGE | INVALID_PARAMETER_RANGE | correct | correct | validate_parameter | validate_parameter | 1.0 | no (0) | EVIDENCE_SUFFICIENT
P-05 | INVALID_BUSINESS_DATE | INVALID_BUSINESS_DATE | INVALID_BUSINESS_DATE | correct | correct | validate_parameter | validate_parameter | 1.0 | yes (1) | EVIDENCE_SUFFICIENT
P-06 | INVALID_PARAMETER_FORMAT | INVALID_PARAMETER_FORMAT | INVALID_PARAMETER_FORMAT | correct | correct | - | validate_parameter | 1.0 | no (0) | NO_ACTIONABLE_TOOL
D-01 | DB_CREDENTIAL_MISMATCH | DB_CREDENTIAL_MISMATCH | DB_CREDENTIAL_MISMATCH | correct | correct | check_db_status | check_db_status | 1.0 | no (0) | EVIDENCE_SUFFICIENT
D-02 | DB_ACCOUNT_LOCKED | DB_ACCOUNT_LOCKED | DB_ACCOUNT_LOCKED | correct | correct | check_db_status | check_db_status | 1.0 | no (0) | EVIDENCE_SUFFICIENT
D-03 | DB_CONNECTION_CONFIG_ERROR | DB_CONNECTION_CONFIG_ERROR | DB_CONNECTION_CONFIG_ERROR | correct | correct | check_db_status | check_db_status | 1.0 | no (0) | EVIDENCE_SUFFICIENT
D-04 | DB_ACCOUNT_LOCKED | DB_ACCOUNT_LOCKED | DB_ACCOUNT_LOCKED | correct | correct | check_db_status | check_db_status | 1.0 | no (0) | EVIDENCE_SUFFICIENT
D-05 | DB_CREDENTIAL_MISMATCH | DB_CREDENTIAL_MISMATCH | DB_CREDENTIAL_MISMATCH | correct | correct | - | - | 1.0 | no (0) | EVIDENCE_SUFFICIENT
D-06 | DB_CONNECTION_CONFIG_ERROR | DB_CONNECTION_CONFIG_ERROR | DB_CONNECTION_CONFIG_ERROR | correct | correct | check_db_status | check_db_status | 1.0 | no (0) | EVIDENCE_SUFFICIENT
S-01 | TABLE_NOT_FOUND | TABLE_NOT_FOUND | TABLE_NOT_FOUND | correct | correct | check_sql_metadata | check_sql_metadata | 1.0 | no (0) | EVIDENCE_SUFFICIENT
S-02 | COLUMN_NOT_FOUND | COLUMN_NOT_FOUND | COLUMN_NOT_FOUND | correct | correct | check_sql_metadata | check_sql_metadata | 1.0 | no (0) | EVIDENCE_SUFFICIENT
S-03 | INVALID_SCHEMA | INVALID_SCHEMA | INVALID_SCHEMA | correct | correct | check_sql_metadata | check_sql_metadata | 1.0 | no (0) | EVIDENCE_SUFFICIENT
S-04 | TABLE_NOT_FOUND | TABLE_NOT_FOUND | TABLE_NOT_FOUND | correct | correct | check_sql_metadata | check_sql_metadata | 1.0 | no (0) | EVIDENCE_SUFFICIENT
S-05 | COLUMN_NOT_FOUND | COLUMN_NOT_FOUND | COLUMN_NOT_FOUND | correct | correct | check_sql_metadata | check_sql_metadata | 1.0 | no (0) | EVIDENCE_SUFFICIENT
S-06 | INVALID_SCHEMA | INVALID_SCHEMA | INVALID_SCHEMA | correct | correct | check_sql_metadata | check_sql_metadata | 1.0 | no (0) | DUPLICATE_TOOL_CALL_BLOCKED
C-01 | DB_ACCOUNT_LOCKED | DB_ACCOUNT_LOCKED | DB_ACCOUNT_LOCKED | correct | correct | check_db_status | check_db_status | 1.0 | yes (1) | EVIDENCE_SUFFICIENT
C-02 | INVALID_BUSINESS_DATE | INVALID_BUSINESS_DATE | INVALID_BUSINESS_DATE | correct | correct | check_file_status, validate_parameter | check_file_status, validate_parameter | 1.0 | no (0) | EVIDENCE_SUFFICIENT
C-03 | TABLE_NOT_FOUND | TABLE_NOT_FOUND | TABLE_NOT_FOUND | correct | correct | check_sql_metadata, check_db_status | check_sql_metadata, check_db_status | 1.0 | no (0) | EVIDENCE_SUFFICIENT
C-04 | TABLE_NOT_FOUND | TABLE_NOT_FOUND | TABLE_NOT_FOUND | correct | correct | check_sql_metadata, check_db_status | check_sql_metadata | 0.5 | no (0) | EVIDENCE_SUFFICIENT
C-05 | FILE_NOT_RECEIVED | FILE_NOT_RECEIVED | FILE_NOT_RECEIVED | correct | correct | - | - | 1.0 | no (0) | MISSING_REQUIRED_ARGUMENTS
C-06 | INVALID_BUSINESS_DATE | INVALID_BUSINESS_DATE | INVALID_BUSINESS_DATE | correct | correct | check_file_status, validate_parameter | check_file_status, validate_parameter | 1.0 | no (0) | EVIDENCE_SUFFICIENT

## V1에서 틀리고 V2에서 맞은 케이스

- F-05: GT `INVALID_BUSINESS_DATE`. V1은 `check_file_status`만 호출하고 `FILE_NOT_RECEIVED`. V2는 `check_file_status` SUCCESS 후 Re-plan으로 `validate_parameter`를 호출, `is_valid=false`/`expected_value=20260901`을 보고 `INVALID_BUSINESS_DATE`, `확인됨`, `stop_reason=EVIDENCE_SUFFICIENT`. Required Tool Recall 0.5 → 1.0. 초기 가설에는 `INVALID_BUSINESS_DATE`가 없음 (Hypothesis Recall false 유지).

## V1에서 맞았는데 V2에서 틀린 regression

- F-02: GT `INVALID_FILE_PATH` (`sale_20260901.csv` vs 같은 디렉터리 `sales_20260901.csv`). V1은 `check_file_status`만으로 `INVALID_FILE_PATH` 정답. V2는 같은 파일 Tool 후 `validate_parameter`를 추가 호출(`is_valid=true`)했고, Planner도 `same_directory_files`의 유사 파일명을 언급했으나 finalizer는 `FILE_NOT_RECEIVED`로 확정. `stop_reason=NO_ACTIONABLE_TOOL`. 설계상 F-04와 같은 evidence interpretation / V3 영역. 다만 F-02는 V1 정답 케이스이므로 이번 30건에서 accuracy가 제자리인 직접 원인이다.

## 둘 다 틀린 케이스

- F-04: GT `INVALID_FILE_PATH`. V1/V2 모두 `FILE_NOT_RECEIVED`. V2는 `validate_parameter`를 추가 호출(unnecessary). Planner는 `partner` vs `partnr` 오타 가능성을 적었지만 finalizer는 파일 미수신으로 확정. V3 대상이며 V2 실패로 과도하게 해석하지 않음.

## Unnecessary Tool 변화

V1 6.7% → V2 15.0%. 크게 상승. F-05를 맞추기 위한 일반 Re-plan 규칙이 FILE 케이스에 넓게 적용됨.

- 유지: P-05, C-01 (NOT_NEEDED인데 V1과 같이 Tool 1회). V2가 불필요 호출을 줄이지 못함.
- 신규 증가: F-01, F-02, F-03, F-04, F-06에서 `validate_parameter` 추가. required는 `check_file_status`뿐.
- F-05의 `validate_parameter`는 required이므로 unnecessary가 아님.

FILE 그룹에서 파일 없음 SUCCESS 이후 business_date를 항상 한 번 더 보는 패턴이다. F-05에서는 이 패턴이 근본 원인을 갈랐고, F-01/F-03/F-06에서는 최종 원인은 맞았지만 불필요 Tool이 늘었다. F-02/F-04에서는 같은 추가 호출이 해석을 바꾸지 못했거나(F-04) 오히려 V1 정답을 놓쳤다(F-02).

## Required Tool Recall 변화

V1 95.0% → V2 98.3%.

- F-05: 0.5 → 1.0 (개선, Re-plan)
- P-06: 0.0 → 1.0. V1은 Tool 0회, V2는 `validate_parameter`를 호출했으나 FAILED (`알 수 없는 job_name`). 최종 원인은 로그 문구로 동일하게 정답. Recall만 오른 케이스.
- C-04: 1.0 → 0.5. V2는 `check_sql_metadata`만 호출하고 `check_db_status`를 생략. 로그에 DB connection OK가 있어 Planner가 SQL SUCCESS만으로 `EVIDENCE_SUFFICIENT` 판정. 최종 원인은 `TABLE_NOT_FOUND`로 정답이지만 required tool 일부 누락.

## 특정 케이스

### F-05

대표 성공. `check_file_status` → Re-plan → `validate_parameter` → `INVALID_BUSINESS_DATE` / `확인됨` / `EVIDENCE_SUFFICIENT`. Tool Recall 1.0. 단순 Tool 나열이 아니라 파일 없음만으로는 원인이 갈리지 않는다는 sufficiency 판단 후 추가 조사.

### F-04

V3 대상. 오답 유지. V2는 `validate_parameter` 과조사 1회. Planner는 유사 파일명을 봤지만 최종은 `FILE_NOT_RECEIVED`.

### P-05 / C-01

둘 다 NOT_NEEDED. V2도 V1과 같이 각각 `validate_parameter`, `check_db_status`를 호출. 불필요 Tool 감소 없음. 최종 원인과 level은 정답.

### FAILED Tool (F-06 / D-06 / S-06 / C-06)

FAILED error 문자열이 최종 evidence에 들어간 케이스 없음.

- F-06: tools FAILED 2개, evidence는 로그만, `diagnosis_level=추정`, `NO_ACTIONABLE_TOOL`. 다만 unnecessary `validate_parameter` 1회.
- D-06: `check_db_status` FAILED, evidence는 ORA-12154 로그, `추정`, `EVIDENCE_SUFFICIENT`.
- S-06: `check_sql_metadata` FAILED 후 동일 fingerprint 재시도가 막혀 `DUPLICATE_TOOL_CALL_BLOCKED`. evidence는 로그, `추정`.
- C-06: file Tool FAILED + `validate_parameter` SUCCESS. evidence는 SUCCESS 파라미터와 로그. FAILED 경로 카탈로그 오류는 evidence에 없음. `확인됨` / `INVALID_BUSINESS_DATE`.

### C-04

복합 조사. V1은 `check_sql_metadata` + `check_db_status`. V2는 SQL만 호출하고 round 2에서 `EVIDENCE_SUFFICIENT`. Re-plan 라운드는 있으나 두 번째 Tool은 실행하지 않음. 로그의 DB connection OK를 sufficiency로 본 것. 최종 원인은 정답, required recall 0.5.

## 개선이 Re-planning인지 Tool 증가인지

- F-05: evidence sufficiency + Re-planning. 두 번째 Tool이 required이고 SUCCESS data가 원인을 가름.
- P-06 Tool Recall 상승: 호출 증가. Tool은 FAILED라 최종 근거가 되지 않음.
- FILE 5건의 unnecessary `validate_parameter`: 일반화된 추가 호출. F-01/F-03 정답 유지와 무관하거나, F-02 regression / F-04 미해결과 함께 나타남.
- F-02 regression: 추가 Tool이 정답을 만든 것이 아니라, 같은 파일 evidence를 표면 증상으로 재해석한 결과.

## 성공 기준 대비

- F-05 개선: 충족
- V1 정답 케이스 심각한 regression 없음: **미충족**. F-02가 V1 정답 → V2 오답
- failed_runs = 0: 충족
- Required Tool Recall ≥ 95.0%: 충족 (98.3%)
- Unnecessary Tool Rate 증가 여부: **증가함** 6.7% → 15.0%
- Final Diagnosis Accuracy > 93.3%: **제자리** 93.3% (28/30). F-05 이득이 F-02 손실과 상쇄

이 문서는 raw 결과 고정용이다. 평가 후 Agent/Prompt/GT를 튜닝하지 않았다.
