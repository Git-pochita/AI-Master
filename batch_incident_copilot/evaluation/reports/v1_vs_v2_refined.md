# V1 vs V2 vs V2 refined Evaluation

## 평가 조건

- Ground Truth 30건 동일. GT/V0/V1 prompt 미수정
- V1: 공식 `v1_summary.json` (재실행 없음)
- V2 1차: `v2_summary.json` / `v1_vs_v2.md` (이 평가에서 덮어쓰지 않음)
- V2 refined: 추가 조사 concrete-signal 가드 적용 후 `run_evaluation.py --versions v2`
- 모델: Azure OpenAI `gpt-4.1`
- Hypothesis Recall은 initial_hypotheses 기준이며 V2 KPI가 아님

## 비교표

Metric | V1 | V2 1차 | V2 refined
--- | --- | --- | ---
Final Diagnosis Accuracy | 93.3% (28/30) | 93.3% (28/30) | 93.3% (28/30)
Hypothesis Recall | 86.7% | 86.7% | 86.7%
Diagnosis Level Accuracy | 100.0% | 100.0% | 100.0%
Owner Accuracy | 100.0% | 100.0% | 100.0%
Required Tool Recall | 95.0% | 98.3% | 98.3%
Unnecessary Tool Rate | 6.7% | 15.0% | 6.7%
failed_runs | 0 | 0 | 0
평균 실행시간 | 14.57초/건 | 18.478초/건 | 17.456초/건

## 케이스별 결과

case_id | actual | V1 | V2 1차 | V2 refined | V1 tools | V2 1차 tools | V2 refined tools | V2 refined stop
--- | --- | --- | --- | --- | --- | --- | --- | ---
F-01 | FILE_NOT_RECEIVED | correct | correct | correct | check_file_status | check_file_status, validate_parameter | check_file_status | EVIDENCE_SUFFICIENT
F-02 | INVALID_FILE_PATH | correct | incorrect | incorrect | check_file_status | check_file_status, validate_parameter | check_file_status | EVIDENCE_SUFFICIENT
F-03 | FILE_NOT_RECEIVED | correct | correct | correct | check_file_status | check_file_status, validate_parameter | check_file_status | EVIDENCE_SUFFICIENT
F-04 | INVALID_FILE_PATH | incorrect | incorrect | incorrect | check_file_status | check_file_status, validate_parameter | check_file_status | EVIDENCE_SUFFICIENT
F-05 | INVALID_BUSINESS_DATE | incorrect | correct | correct | check_file_status | check_file_status, validate_parameter | check_file_status, validate_parameter | EVIDENCE_SUFFICIENT
F-06 | FILE_NOT_RECEIVED | correct | correct | correct | check_file_status | check_file_status, validate_parameter | check_file_status | NO_ACTIONABLE_TOOL
P-01 | INVALID_BUSINESS_DATE | correct | correct | correct | validate_parameter | validate_parameter | validate_parameter | EVIDENCE_SUFFICIENT
P-02 | MISSING_REQUIRED_PARAMETER | correct | correct | correct | validate_parameter | validate_parameter | validate_parameter | EVIDENCE_SUFFICIENT
P-03 | INVALID_PARAMETER_FORMAT | correct | correct | correct | validate_parameter | validate_parameter | validate_parameter | EVIDENCE_SUFFICIENT
P-04 | INVALID_PARAMETER_RANGE | correct | correct | correct | validate_parameter | validate_parameter | validate_parameter | EVIDENCE_SUFFICIENT
P-05 | INVALID_BUSINESS_DATE | correct | correct | correct | validate_parameter | validate_parameter | validate_parameter | EVIDENCE_SUFFICIENT
P-06 | INVALID_PARAMETER_FORMAT | correct | correct | correct | - | validate_parameter | validate_parameter | EVIDENCE_SUFFICIENT
D-01 | DB_CREDENTIAL_MISMATCH | correct | correct | correct | check_db_status | check_db_status | check_db_status | EVIDENCE_SUFFICIENT
D-02 | DB_ACCOUNT_LOCKED | correct | correct | correct | check_db_status | check_db_status | check_db_status | EVIDENCE_SUFFICIENT
D-03 | DB_CONNECTION_CONFIG_ERROR | correct | correct | correct | check_db_status | check_db_status | check_db_status | EVIDENCE_SUFFICIENT
D-04 | DB_ACCOUNT_LOCKED | correct | correct | correct | check_db_status | check_db_status | check_db_status | EVIDENCE_SUFFICIENT
D-05 | DB_CREDENTIAL_MISMATCH | correct | correct | correct | - | - | - | EVIDENCE_SUFFICIENT
D-06 | DB_CONNECTION_CONFIG_ERROR | correct | correct | correct | check_db_status | check_db_status | check_db_status | EVIDENCE_SUFFICIENT
S-01 | TABLE_NOT_FOUND | correct | correct | correct | check_sql_metadata | check_sql_metadata | check_sql_metadata | EVIDENCE_SUFFICIENT
S-02 | COLUMN_NOT_FOUND | correct | correct | correct | check_sql_metadata | check_sql_metadata | check_sql_metadata | EVIDENCE_SUFFICIENT
S-03 | INVALID_SCHEMA | correct | correct | correct | check_sql_metadata | check_sql_metadata | check_sql_metadata | EVIDENCE_SUFFICIENT
S-04 | TABLE_NOT_FOUND | correct | correct | correct | check_sql_metadata | check_sql_metadata | check_sql_metadata | EVIDENCE_SUFFICIENT
S-05 | COLUMN_NOT_FOUND | correct | correct | correct | check_sql_metadata | check_sql_metadata | check_sql_metadata | EVIDENCE_SUFFICIENT
S-06 | INVALID_SCHEMA | correct | correct | correct | check_sql_metadata | check_sql_metadata | check_sql_metadata | EVIDENCE_SUFFICIENT
C-01 | DB_ACCOUNT_LOCKED | correct | correct | correct | check_db_status | check_db_status | check_db_status | EVIDENCE_SUFFICIENT
C-02 | INVALID_BUSINESS_DATE | correct | correct | correct | check_file_status, validate_parameter | check_file_status, validate_parameter | check_file_status, validate_parameter | EVIDENCE_SUFFICIENT
C-03 | TABLE_NOT_FOUND | correct | correct | correct | check_sql_metadata, check_db_status | check_sql_metadata, check_db_status | check_sql_metadata, check_db_status | EVIDENCE_SUFFICIENT
C-04 | TABLE_NOT_FOUND | correct | correct | correct | check_sql_metadata, check_db_status | check_sql_metadata | check_sql_metadata | EVIDENCE_SUFFICIENT
C-05 | FILE_NOT_RECEIVED | correct | correct | correct | - | - | - | MISSING_REQUIRED_ARGUMENTS
C-06 | INVALID_BUSINESS_DATE | correct | correct | correct | check_file_status, validate_parameter | check_file_status, validate_parameter | check_file_status, validate_parameter | EVIDENCE_SUFFICIENT

## V2 1차 대비 refined 변화

- F-05 정답 유지. `check_file_status` → `validate_parameter`, recall 1.0
- F-01/F-03/F-04/F-06: 1차의 추가 `validate_parameter` 제거. F-01/F-03/F-06 정답 유지, F-04는 계속 오답(V3)
- F-02: 추가 `validate_parameter`는 제거했으나 최종 원인은 여전히 `FILE_NOT_RECEIVED`. V1 정답(`INVALID_FILE_PATH`) regression 미해소. FILE evidence 해석은 V3 영역이라 Critic을 넣지 않음
- Unnecessary Tool Rate 15.0% → 6.7% (V1과 동일). 남은 unnecessary는 P-05, C-01 (NOT_NEEDED, V1과 동일)
- Required Tool Recall 98.3% 유지 (F-05 1.0, P-06 1.0, C-04 0.5)
- Accuracy 93.3% 유지. F-05 이득이 F-02 손실과 상쇄
- C-02/C-06: 일자 불일치 concrete signal이 있어 file+param Re-plan 유지

이 문서는 raw 결과 고정용이다. 재평가 확인 후 추가 튜닝을 하지 않았다.
