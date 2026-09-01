# V0 vs V1 Evaluation

## 평가 조건

- 총 평가 케이스: 30
- 장애 영역별 건수: COMPOSITE 6건, DB 6건, FILE 6건, PARAMETER 6건, SQL 6건
- Tool 호출 기대(GT metadata): NOT_CALLABLE 2건, NOT_NEEDED 2건, REQUIRED 26건
- Tool 호출 기대 구분: REQUIRED=원인 검증에 Tool 필요, NOT_NEEDED=로그 근거가 충분하여 Tool 불필요, NOT_CALLABLE=필수 인자/근거 부족으로 호출 불가
- Tool Recall / Unnecessary Tool Rate 채점 공식은 변경하지 않았습니다. 위 구분은 해석용 metadata입니다.
- 사용 모델: `gpt-4.1`
- 실행 환경: local/mock PoC. Tool은 로컬 JSON만 조회하며 실제 운영 DB/파일시스템에 접속하지 않습니다.
- execution time이 있어도 로컬 PoC 측정값이며, 운영 장애 분석 시간 절감을 의미하지 않습니다.

## 비교표

Metric | V0 | V1
--- | --- | ---
Final Diagnosis Accuracy | 73.3% | 93.3%
Hypothesis Recall | 86.7% | 86.7%
Diagnosis Level Accuracy | 93.3% | 100.0%
Owner Accuracy | 100.0% | 100.0%
Required Tool Recall | N/A | 95.0%
Unnecessary Tool Rate | N/A | 6.7%

## 케이스별 결과

case_id | actual cause | V0 final cause | V1 final cause | V1 selected tools | V0 | V1
--- | --- | --- | --- | --- | --- | ---
F-01 | FILE_NOT_RECEIVED | FILE_NOT_RECEIVED | FILE_NOT_RECEIVED | check_file_status | correct | correct
F-02 | INVALID_FILE_PATH | FILE_NOT_RECEIVED | INVALID_FILE_PATH | check_file_status | incorrect | correct
F-03 | FILE_NOT_RECEIVED | FILE_NOT_RECEIVED | FILE_NOT_RECEIVED | check_file_status | correct | correct
F-04 | INVALID_FILE_PATH | FILE_NOT_RECEIVED | FILE_NOT_RECEIVED | check_file_status | incorrect | incorrect
F-05 | INVALID_BUSINESS_DATE | FILE_NOT_RECEIVED | FILE_NOT_RECEIVED | check_file_status | incorrect | incorrect
F-06 | FILE_NOT_RECEIVED | FILE_NOT_RECEIVED | FILE_NOT_RECEIVED | check_file_status | correct | correct
P-01 | INVALID_BUSINESS_DATE | INVALID_BUSINESS_DATE | INVALID_BUSINESS_DATE | validate_parameter | correct | correct
P-02 | MISSING_REQUIRED_PARAMETER | MISSING_REQUIRED_PARAMETER | MISSING_REQUIRED_PARAMETER | validate_parameter | correct | correct
P-03 | INVALID_PARAMETER_FORMAT | INVALID_PARAMETER_RANGE | INVALID_PARAMETER_FORMAT | validate_parameter | incorrect | correct
P-04 | INVALID_PARAMETER_RANGE | INVALID_PARAMETER_RANGE | INVALID_PARAMETER_RANGE | validate_parameter | correct | correct
P-05 | INVALID_BUSINESS_DATE | INVALID_BUSINESS_DATE | INVALID_BUSINESS_DATE | validate_parameter | correct | correct
P-06 | INVALID_PARAMETER_FORMAT | INVALID_PARAMETER_FORMAT | INVALID_PARAMETER_FORMAT | - | correct | correct
D-01 | DB_CREDENTIAL_MISMATCH | DB_CREDENTIAL_MISMATCH | DB_CREDENTIAL_MISMATCH | check_db_status | correct | correct
D-02 | DB_ACCOUNT_LOCKED | DB_CREDENTIAL_MISMATCH | DB_ACCOUNT_LOCKED | check_db_status | incorrect | correct
D-03 | DB_CONNECTION_CONFIG_ERROR | DB_CONNECTION_CONFIG_ERROR | DB_CONNECTION_CONFIG_ERROR | check_db_status | correct | correct
D-04 | DB_ACCOUNT_LOCKED | DB_CREDENTIAL_MISMATCH | DB_ACCOUNT_LOCKED | check_db_status | incorrect | correct
D-05 | DB_CREDENTIAL_MISMATCH | DB_CREDENTIAL_MISMATCH | DB_CREDENTIAL_MISMATCH | - | correct | correct
D-06 | DB_CONNECTION_CONFIG_ERROR | DB_CONNECTION_CONFIG_ERROR | DB_CONNECTION_CONFIG_ERROR | check_db_status | correct | correct
S-01 | TABLE_NOT_FOUND | TABLE_NOT_FOUND | TABLE_NOT_FOUND | check_sql_metadata | correct | correct
S-02 | COLUMN_NOT_FOUND | COLUMN_NOT_FOUND | COLUMN_NOT_FOUND | check_sql_metadata | correct | correct
S-03 | INVALID_SCHEMA | INVALID_SCHEMA | INVALID_SCHEMA | check_sql_metadata | correct | correct
S-04 | TABLE_NOT_FOUND | TABLE_NOT_FOUND | TABLE_NOT_FOUND | check_sql_metadata | correct | correct
S-05 | COLUMN_NOT_FOUND | COLUMN_NOT_FOUND | COLUMN_NOT_FOUND | check_sql_metadata | correct | correct
S-06 | INVALID_SCHEMA | INVALID_SCHEMA | INVALID_SCHEMA | check_sql_metadata | correct | correct
C-01 | DB_ACCOUNT_LOCKED | DB_ACCOUNT_LOCKED | DB_ACCOUNT_LOCKED | check_db_status | correct | correct
C-02 | INVALID_BUSINESS_DATE | FILE_NOT_RECEIVED | INVALID_BUSINESS_DATE | check_file_status, validate_parameter | incorrect | correct
C-03 | TABLE_NOT_FOUND | TABLE_NOT_FOUND | TABLE_NOT_FOUND | check_sql_metadata, check_db_status | correct | correct
C-04 | TABLE_NOT_FOUND | TABLE_NOT_FOUND | TABLE_NOT_FOUND | check_sql_metadata, check_db_status | correct | correct
C-05 | FILE_NOT_RECEIVED | FILE_NOT_RECEIVED | FILE_NOT_RECEIVED | - | correct | correct
C-06 | INVALID_BUSINESS_DATE | FILE_NOT_RECEIVED | INVALID_BUSINESS_DATE | check_file_status, validate_parameter | incorrect | correct
