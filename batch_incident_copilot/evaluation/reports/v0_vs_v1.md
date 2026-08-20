# V0 vs V1 Evaluation

## 평가 조건

- 총 평가 케이스: 10
- 장애 영역별 건수: DB 2건, FILE 3건, PARAMETER 3건, SQL 2건
- 사용 모델: `gpt-4.1`
- 실행 환경: local/mock PoC. Tool은 로컬 JSON만 조회하며 실제 운영 DB/파일시스템에 접속하지 않습니다.
- execution time이 있어도 로컬 PoC 측정값이며, 운영 장애 분석 시간 절감을 의미하지 않습니다.

## 비교표

Metric | V0 | V1
--- | --- | ---
Final Diagnosis Accuracy | 70.0% | 90.0%
Hypothesis Recall | 80.0% | 80.0%
Diagnosis Level Accuracy | 100.0% | 100.0%
Owner Accuracy | 100.0% | 100.0%
Required Tool Recall | N/A | 100.0%
Unnecessary Tool Rate | N/A | 5.0%

## 케이스별 결과

case_id | actual cause | V0 final cause | V1 final cause | V1 selected tools | V0 | V1
--- | --- | --- | --- | --- | --- | ---
file_case_001 | INVALID_BUSINESS_DATE | FILE_NOT_RECEIVED | INVALID_BUSINESS_DATE | check_file_status, validate_parameter | incorrect | correct
file_case_002 | FILE_NOT_RECEIVED | FILE_NOT_RECEIVED | FILE_NOT_RECEIVED | check_file_status | correct | correct
file_case_003 | INVALID_FILE_PATH | FILE_NOT_RECEIVED | FILE_NOT_RECEIVED | check_file_status, validate_parameter | incorrect | incorrect
db_case_001 | DB_CREDENTIAL_MISMATCH | DB_CREDENTIAL_MISMATCH | DB_CREDENTIAL_MISMATCH | check_db_status | correct | correct
db_case_002 | DB_ACCOUNT_LOCKED | DB_CREDENTIAL_MISMATCH | DB_ACCOUNT_LOCKED | check_db_status | incorrect | correct
sql_case_001 | TABLE_NOT_FOUND | TABLE_NOT_FOUND | TABLE_NOT_FOUND | check_sql_metadata | correct | correct
sql_case_002 | COLUMN_NOT_FOUND | COLUMN_NOT_FOUND | COLUMN_NOT_FOUND | check_sql_metadata | correct | correct
param_case_001 | MISSING_REQUIRED_PARAMETER | MISSING_REQUIRED_PARAMETER | MISSING_REQUIRED_PARAMETER | validate_parameter | correct | correct
param_case_002 | INVALID_PARAMETER_FORMAT | INVALID_PARAMETER_FORMAT | INVALID_PARAMETER_FORMAT | validate_parameter | correct | correct
param_case_003 | INVALID_PARAMETER_RANGE | INVALID_PARAMETER_RANGE | INVALID_PARAMETER_RANGE | validate_parameter | correct | correct
