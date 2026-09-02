# V3 Official Critic Error Analysis

분석 전용 문서. V3 코드/prompt/GT/evaluator를 변경하지 않는다. 공식 30건을 재실행하지 않는다.

출처:

- 기준 main: `58f4942e801af8199af614b1a98bee0735ef3b97` (PR #17 merge)
- `results/v3_critic/F-01.json` … `F-05.json`
- `evaluation/reports/v3_summary.json`, `v2_refined_vs_v3.md`
- `app/critic.py` `build_critic_input()`, `cause_revision_allowed()`
- `prompts/v3_critic_prompt.txt`
- sample logs: `data/sample_logs/F-0{1,2,3,4,5}.log`

Critic 입력은 저장된 V3 payload에서 V2 필드(`original_v2_*`, `extracted_info`, `tool_results`, PASS 케이스의 `evidence`)와 실제 sample log로 `build_critic_input()`을 재호출해 재구성했다. F-05의 V3 `evidence`는 Revision 이후 값일 수 있어, Critic이 본 V2 evidence 목록은 별도로 구분한다.

---

## 1. Official baseline 요약

공식 V3 1회 실행 (`gpt-4.1`):

| KPI | 값 |
| --- | --- |
| Final Diagnosis Accuracy | 93.3% (28/30) |
| Critic Revision Count | 1 |
| Critic Revision Precision | 0.0 |
| Unnecessary Revision Rate | 0.0 |
| Net Corrected | 0 |
| Regression | 0 |
| FAILED evidence misuse | 0 |

 Critic 분류:

| category | count | cases |
| --- | --- | --- |
| PASS + V2 correct | 27 | 대부분 |
| PASS + V2 wrong | 2 | F-02, F-04 |
| REVISE + unchanged | 1 | F-05 |
| REVISE + corrected / regression / still wrong | 0 | - |

이 문서의 대상은 false negative 2건(F-02/F-04)과 false positive Critic 1건(F-05)이다.

---

## 2. F-02 분석

### 2.1 Official 결과

- V2 / V3 final: `FILE_NOT_RECEIVED`
- expected: `INVALID_FILE_PATH`
- Critic: `PASS`, `issues=[]`, `evidence_consistent=true`, `revised=false`
- Gate: 호출되지 않음 (PASS라 Revision 없음)

### 2.2 재구성한 Critic 입력

`build_critic_input()` allowlist만 존재. denylist 키(`case_id`, `ground_truth`, `actual_cause_code`, `planning_trace`, `selected_tools`, `summary`, `investigation_plan` 등)는 payload top-level에 없음. 저장된 `planning_trace[].reason` / `selected_tools[].reason` 전문은 재구성 입력 JSON에 포함되지 않았다.

| 필드 | 실제 전달 값 |
| --- | --- |
| log | `JOB=DAILY_SALES_LOAD`, `business_date=20260901`, `input=/data/in/sale_20260901.csv`, `FileNotFoundError: /data/in/sale_20260901.csv`, `return_code=12` |
| extracted_info | job=`DAILY_SALES_LOAD`, business_date=`20260901`, input_path=`/data/in/sale_20260901.csv` |
| V2 final_cause_code | `FILE_NOT_RECEIVED` |
| diagnosis_level / owner | `확인됨` / `BATCH_OPERATION` |
| filtered evidence | 대상 경로 `exists=false, received=false`; 로그 FileNotFound; return_code=12. **sibling 파일명 없음** |
| SUCCESS tool | `check_file_status` 1건. raw `data.same_directory_files`에 `sales_20260901.csv` exists=true, received=true 포함 |
| canonical_causes | vocabulary 전체 (FILE/DB/SQL/PARAMETER) |

### 2.3 SUCCESS field matrix

| field | 값 | FILE_NOT_RECEIVED | INVALID_FILE_PATH |
| --- | --- | --- | --- |
| requested path | `/data/in/sale_20260901.csv` | 대상 미수신과 양립 | 잘못된 파일명과 양립 |
| requested filename | `sale_20260901.csv` | 대상이 없음 | `sale` vs `sales` 오타 후보 |
| target exists | false | 지지 | 지지 (둘 다) |
| target received | false | 지지 | 지지 (둘 다) |
| sibling `sales_20260901.csv` | exists=true, received=true | **설명하지 못함** (같은 날짜·유사 이름이 수신됨) | 대상만 잘못된 경로일 때 더 잘 설명 |
| sibling `ledger_20260901.csv` | received=true | 디렉터리 자체는 살아 있음. 단독으로 어느 원인도 확정하지 않음 | 경로 디렉터리 유효를 약하게 지지 |
| sibling `sales_20260831.csv` / `ledger_20260831.csv` | received=false | 전일 미수신. 오타 근거 아님 | 어느 쪽도 아님 |
| business_date vs filename | 둘 다 `20260901` | 날짜 불일치 없음 | 날짜가 아니라 파일명 철자 쪽 |

`FILE_NOT_RECEIVED`가 설명하는 것: 요청 파일이 없고 로그가 FileNotFound인 것.  
설명하지 못하는 것: **같은 날짜의 유사 파일명 `sales_20260901.csv`가 이미 수신됨.**

### 2.4 PASS 직접 원인

1. V2 `evidence[]`는 대상 missing만 적고 sibling을 빼서, 표면 채널이 `FILE_NOT_RECEIVED`와 동어반복이다.
2. sibling contrast는 `success_tool_results[].data.same_directory_files` 중첩 배열에만 있다. Critic은 이를 받지만, prompt가 “supporting vs contradicting field를 나열하라”고 강제하지 않는다.
3. prompt 기본값이 PASS이고, “대상 파일이 없다는 사실만으로는 conflict로 두지 말라”고 명시한다. 이 문장은 F-01 보호용이나, sibling 수신을 언제 conflict로 볼지는 말하지 않는다.
4. Deterministic Critic은 FAILED evidence / level cap / empty owner만 본다. sibling contrast는 LLM 몫이다.
5. Gate는 PASS라 개입하지 않았다.

따라서 F-02 실패는 Gate가 아니라 **LLM Critic이 이미 가진 sibling 필드를 conflict로 승격하지 못한 것**이다.

---

## 3. F-04 분석

### 3.1 Official 결과

- V2 / V3 final: `FILE_NOT_RECEIVED`
- expected: `INVALID_FILE_PATH`
- Critic: `PASS`, issues 없음, `revised=false`
- Gate: 미적용

### 3.2 재구성한 Critic 입력

denylist 키 없음. planner/tool reason 미포함. GT/`case_id` 키 없음.

| 필드 | 실제 전달 값 |
| --- | --- |
| log | `JOB=DAILY_PARTNER_LOAD`, `business_date=20260901`, `input=/data/in/partner/partnr_20260901.csv`, FileNotFound |
| extracted_info | job=`DAILY_PARTNER_LOAD`, path=`/data/in/partner/partnr_20260901.csv` |
| V2 cause / level / owner | `FILE_NOT_RECEIVED` / `확인됨` / `BATCH_OPERATION` |
| filtered evidence | 대상 `exists=false, received=false` + 로그만. **`partner_20260901.csv` 없음** |
| SUCCESS tool | `check_file_status`. `same_directory_files`: `partner_20260901.csv` received=true, `partnr_20260901.csv` received=false |

### 3.3 SUCCESS field matrix

| field | 값 | FILE_NOT_RECEIVED | INVALID_FILE_PATH |
| --- | --- | --- | --- |
| requested filename | `partnr_20260901.csv` | 대상 미수신 | 철자 누락 후보 (`partnr` / `partner`) |
| target exists/received | false/false | 지지 | 둘 다 |
| sibling `partner_20260901.csv` | exists=true, received=true | **설명하지 못함** | 대상만 잘못된 파일명일 때 더 잘 설명 |
| 날짜 | 대상·sibling 모두 `20260901` | 날짜 원인 아님 | 날짜 원인 아님 |

filename similarity는 raw SUCCESS에 **별도 “typo score” 필드 없이** 두 `filename` 문자열로만 존재한다. Critic이 contrast로 쓰려면 두 파일명을 나란히 비교해야 한다. 이 문서에서 “문자열이 비슷하므로 INVALID_FILE_PATH” 규칙을 제안하지 않는다.

### 3.4 PASS 직접 원인

F-02와 동일 구조다. evidence[]는 대상 missing만 강조하고, `partner_20260901.csv` received=true는 nested JSON에만 있다. prompt는 동점이면 PASS, 대상 미존재만으로 conflict 금지. LLM은 sibling을 “디렉터리에 다른 파일이 있다” 정도로 보고 current cause와 모순이 아니라고 판단한 것으로 보는 것이 저장된 `issues=[]`와 일치한다.

---

## 4. F-01 / F-03 대조

### 4.1 F-01 SUCCESS

- 대상: `orders_20260901.csv` exists=false, received=false
- sibling: `orders_20260831.csv` **전일 파일**, 역시 exists=false, received=false
- received sibling: **없음**

`FILE_NOT_RECEIVED`는 대상 미수신과 디렉터리 내 다른 수신 파일 부재를 함께 설명한다. 유사 이름·같은 날짜의 수신 파일이 없어 `INVALID_FILE_PATH`를 더 잘 지지하는 필드가 없다.

### 4.2 F-03 SUCCESS

- 대상: `payments_20260901.csv` exists=false, received=false
- `same_directory_files`: 대상 자신만, 역시 missing
- received sibling: **없음**

역시 current cause가 남은 SUCCESS 필드를 모순 없이 설명한다.

### 4.3 일반화 가능한 차이 (case rule 아님)

관측 패턴:

```text
공통: 대상 파일 SUCCESS exists=false, received=false + 로그 읽기 실패
대조: 같은 날짜·유사 이름의 sibling이 received=true 인가?
  아니오 (F-01, F-03) → FILE_NOT_RECEIVED가 SUCCESS 필드를 남김 없이 설명 → PASS가 맞음
  예   (F-02, F-04) → current cause가 sibling 수신을 설명하지 못함 → conflict 후보
```

공식 Critic은 이 두 번째 질문을 입력에서 구조화하지 않았고, prompt도 강제하지 않았다. 그래서 네 케이스 모두 PASS로 수렴했다.

---

## 5. F-05 false positive 분석

### 5.1 Official CriticResult

| 필드 | 값 |
| --- | --- |
| verdict | REVISE |
| evidence_consistent | false |
| diagnosis_level_appropriate | true |
| owner_consistent | true |
| issue 1 | `EVIDENCE_CONFLICT`: `INVALID_BUSINESS_DATE`가 파일 미수신을 직접 설명하지 못함 |
| issue 2 | `BETTER_SUPPORTED_CAUSE`: `FILE_NOT_RECEIVED`가 더 부합 |
| related_evidence | `"check_file_status SUCCESS 결과: /data/in/sales_20260831.csv 파일 존재하지 않음 (exists=false, received=false)"`, `"로그: FileNotFoundError: /data/in/sales_20260831.csv"` |
| recommended_cause_code | `FILE_NOT_RECEIVED` |
| revision_reason | 파일 미수신이 직접 원인이며 `FILE_NOT_RECEIVED`가 더 적합 |
| revised | false |
| 최종 cause | `INVALID_BUSINESS_DATE` (V2 유지) |

### 5.2 Critic이 실제로 본 관찰 가능 정보

- log: `business_date=20260831`, `input=/data/in/sales_20260831.csv`, FileNotFound, 잡 시작 `2026-09-01`
- extracted_info: business_date=`20260831`, path=`.../sales_20260831.csv`
- SUCCESS `check_file_status`: 대상 `sales_20260831.csv` missing; **같은 날 `sales_20260901.csv` received=true**
- SUCCESS `validate_parameter`: `parameter_value=20260831`, `expected_value=20260901`, `job_run_date=20260901`, `is_valid=false`

V3 JSON의 최종 `evidence`는 Revision이 파일 증상만 남긴 목록이다. Critic 입력의 `success_tool_results`에는 **두 Tool이 모두** 들어간다. official V2 refined evidence에도 `validate_parameter SUCCESS ... is_valid=false`가 있다. 즉 Critic은 파라미터 무효 evidence를 볼 수 있었는데도 파일 증상만 conflict로 올렸다.

### 5.3 질문 답

1. **어떤 evidence를 conflict로 봤나?** 대상 파일 missing (`exists=false`, `received=false`)과 FileNotFound 로그.
2. **`INVALID_BUSINESS_DATE`가 그 evidence를 설명 못 하나?** 직접 파일 존재 여부는 설명하지 않는다. 그러나 잘못된 `business_date=20260831`이 `sales_20260831.csv` 경로를 만들면, 실행일(`20260901`)에 해당하는 `sales_20260901.csv`는 수신되어 있고 전일 파일만 없는 현상이 **파라미터 오류의 결과(증상)** 로 설명된다.
3. **표면 증상과 root cause를 혼동했나?** 예. recommended가 `FILE_NOT_RECEIVED`다. 로그/Tool은 “파일이 없다”는 증상과 “날짜 파라미터가 틀렸다”는 원인을 같이 주는데, Critic은 증상을 더 직접적이라고 봤다.
4. **여러 Tool의 causal hierarchy를 못 다뤘나?** 예. prompt는 “중요한 SUCCESS 필드를 current cause가 설명하는가”만 묻고, 한 Tool이 다른 Tool 증상의 원인이 될 수 있는지는 묻지 않는다. `validate_parameter.is_valid=false`가 있는데도 file-missing만으로 REVISE했다.

### 5.4 Gate

`related_evidence` 문자열이 haystack(log / extracted_info / SUCCESS JSON)에 **그대로 있지 않다** (`"로그: FileNotFoundError..."` 접두, 한국어 paraphrase). `cause_revision_allowed()`는 False. Revision이 cause를 `FILE_NOT_RECEIVED`로 바꿔도 되돌린다. `revised=false`.

Gate는 F-05에서 **불필요한 cause 변경을 막았다.** Precision 0.0은 “REVISE가 오답을 고치지 못함”이지 “Gate가 정답을 망가뜨림”이 아니다.

---

## 6. Failure taxonomy

| 후보 | 분류 | 근거 |
| --- | --- | --- |
| Current cause vs contradictory evidence 비교 부족 | **Primary** | F-02/F-04에서 received sibling이 SUCCESS JSON에 있는데도 issues가 비어 있음. prompt/입력이 field별 support/contradict 표를 요구하지 않음 |
| Root cause vs symptom 구분 부족 | **Primary (F-05)** | `validate_parameter` SUCCESS가 있는데 파일 증상을 더 직접 원인으로 승격 |
| Prompt 문제 | **Secondary** | 기본 PASS + “대상 미존재만으로 conflict 금지”가 F-01을 지키지만 F-02/F-04 contrast를 묻지 않음. causal hierarchy 지침 없음 |
| Critic input representation | **Secondary** | V2 `evidence[]`가 sibling/파라미터를 생략하면 LLM이 raw nested JSON을 무시하기 쉬움. denylist 자체는 설계대로 동작 |
| Alternative cause comparison 부족 | **Secondary** | F-02/F-04는 alternative 단계에 도달하지 못함. F-05는 alternative를 골랐으나 증상 코드 |
| Evidence normalization | **Secondary (Gate only)** | F-05 related_evidence가 paraphrase라 Gate가 막음. F-02/F-04 PASS의 원인은 아님 |
| LLM stochasticity | **Secondary** | single-shot. 같은 입력으로 REVISE할 수도 있으나, 두 FILE 오답이 같은 PASS 패턴이라 구조 문제가 더 큼 |
| Gate 문제 | **Not a cause (F-02/F-04)** / **의도대로 동작 (F-05)** | PASS라 Gate 미도달. F-05는 오교정 방지 |
| Deterministic Critic 공백 | 범위 설명 | sibling contrast를 규칙으로 넣지 않은 것은 설계(하드코딩 금지). 공백 자체는 버그가 아니라 LLM에 위임한 결과 |
| GT/case_id leak | **Not a cause** | 재구성 입력에 denylist 키 없음 |

---

## 7. Gate 평가

| 케이스 | Critic | Gate | 판정 |
| --- | --- | --- | --- |
| F-02 | PASS | 실행 안 함 | **실패 원인이 아님** |
| F-04 | PASS | 실행 안 함 | **실패 원인이 아님** |
| F-05 | REVISE + recommended `FILE_NOT_RECEIVED` | False (paraphrase token) | **오답으로의 cause 변경을 차단. 역할 수행** |

공식 Unnecessary Revision Rate 0.0의 직접 방어선은 F-05에서 Gate였다. F-02/F-04를 Gate를 느슨하게 해서 고칠 수는 없다. 탐지가 먼저다.

---

## 8. 개선 후보 비교

구현하지 않는다. 후보만 비교한다.

### A. Prompt-only

Critic prompt에 supporting / contradicting / alternative coverage를 명시적으로 쓰게 한다.

### B. Structured evidence comparison

결정적 코드가 SUCCESS payload를 요약해 전달:

```text
Current Cause
Supporting Evidence
Potentially Contradicting Evidence
Alternative Candidates (canonical names only, 정답 미지정)
```

정답 cause는 코드가 고르지 않는다. `same_directory_files → INVALID_FILE_PATH` 규칙은 넣지 않는다. 예: “요청 파일과 다른 filename이 received=true인 SUCCESS 행”을 contradict 칸에 올리기만 한다.

### C. Two-stage Critic

1) current cause가 중요 필드를 모두 설명하는가. 2) conflict일 때만 canonical alternative 비교. F-05에는 “다른 SUCCESS Tool이 이 증상의 원인인가?”를 1단계에 넣을 수 있다.

| 항목 | A Prompt-only | B Structured comparison | C Two-stage |
| --- | --- | --- | --- |
| F-02/F-04 탐지 가능성 | 중간. sibling이 이미 JSON에 있음. 다만 evidence[] 편향과 기본 PASS가 남음 | 높음. contradict 칸에 received sibling이 명시됨 | 높음. 1단계에서 “설명 안 되는 필드”를 강제 |
| F-01/F-03 regression | 중간. prompt를 세게 쓰면 전일 missing sibling도 conflict로 오인 가능 | 낮음~중간. received=true인 다른 파일만 contradict로 올리면 F-01/F-03은 비어 있음 | 중간. 1단계 질문이 과하면 빈 디렉터리도 conflict |
| F-05 false positive | 중간~높음. file-missing을 더 강조하면 FP 증가 | 중간. validate_parameter를 supporting에 올리면 hierarchy를 보기 쉬움. 안 올리면 FP 유지 | 낮음~중간. 1단계에 “다른 SUCCESS가 증상 원인인가”를 넣으면 FP 감소에 유리 |
| 하드코딩 위험 | 낮음. 케이스명만 안 넣으면 됨 | 중간. contradict 추출 규칙이 사실상 정답을 암시하지 않게 설계해야 함 | 낮음. 질문은 일반적 |
| 구현 복잡도 | 낮음 | 중간 | 중간 (Critic 2회 또는 2블록) |
| 추가 latency | 거의 없음 | 거의 없음 (결정적 전처리) | Critic LLM 1회 추가 가능 |
| Agentic 설명력 | 약함. 왜 PASS인지 구조가 안 남음 | 강함. support/contradict가 이벤트·UI로 남음 | 강함. sufficiency와 alternative가 분리됨 |

---

## 9. 권고안

**B를 주 변경으로 하고, A의 비교 질문과 C의 hierarchy 질문 일부를 B 입력/prompt에 합친다.** A만으로 끝내지 않는다.

이유 (공식 숫자 기준):

- 민감도: F-02/F-04는 데이터가 이미 SUCCESS JSON에 있다. 문제는 비교를 안 한 것이다. contradict 칸이 없으면 prompt를 세게 써도 nested 배열을 다시 무시할 수 있다.
- 보수성: official U=0, F-05 Gate가 오교정을 막았다. prompt만 공격적으로 바꾸면 F-05 FP와 F-01 PASS가 같이 흔들린다.
- B는 정답을 정하지 않고 “received=true인 비대상 파일” 같은 **관찰 필드**만 보여 준다. F-01/F-03은 그 칸이 비므로 기본 PASS를 유지하기 쉽다.
- F-05는 `validate_parameter` 행을 Current Cause supporting에 넣고, file-missing을 “설명되는 증상인지” 묻게 하면 symptom/root 혼동을 줄일 수 있다.

C 단독(Critic 2회)은 latency와 루프 복잡도 대비, 지금 병목이 “2단계 alternative”가 아니라 “1단계에서 conflict를 못 봄 / 증상을 conflict로 오인”이라 우선순위가 낮다.

---

## 10. V3.1 여부 및 다음 단계

**추천: B. V3.1을 한 번만 개선.**

- 현재 V3를 최종 PoC로 두기에는 official 목표가 F-02/F-04 개선이었고 Net Corrected=0이다. baseline으로는 유효하나 닫기엔  mon가 분명하다.
- 더 큰 구조(새 Tool, Re-plan+Critic 혼합, RAG)는 이 세 케이스를 설명하지 않는다. 데이터는 이미 있다.

V3.1을 한다면 (구현하지 않음):

변경 범위:

- Critic 입력 전처리: SUCCESS 필드를 support / potential-contradict로 요약 (정답 미결정)
- Critic prompt: 그 칸을 비교하고, 다른 SUCCESS Tool이 증상을 설명하면 conflict로 보지 말 것
- 기존 Gate는 유지. paraphrase token 문제는 related_evidence를 raw 필드 값으로 쓰라고만 지시

변경하지 않을 것:

- `diagnose_v2()`, V2 prompt, `has_parameter_anomaly_signal()`
- GT, 기존 V0/V1/V2/V3 official report
- Cause vocabulary, evaluator 공식
- F-02/F-04 `case_id` 분기, `same_directory_files → INVALID_FILE_PATH` 규칙
- 추가 Tool, Critic 무한 루프

새 평가 전 deterministic tests (제안만):

- received sibling이 SUCCESS에 있으면 contradict 칸에 그 filename이 나타남 (정답 cause 단정 없음)
- F-01형: received sibling 없으면 contradict 칸 비어 있고 mock PASS 유지
- F-05형: `is_valid=false`가 supporting에 있고, file-missing만으로 mock REVISE해도 Gate/정책이 V2 cause를 유지하거나 hierarchy 질문이 막음
- 기존 F-01…F-06 / P-05 / D-01 / C-06 guard와 164+ tests 유지

다음 공식 30건은 V3.1 freeze 후 **한 번만**. 이 분석 문서 작성 단계에서는 구현·재평가를 하지 않는다.
