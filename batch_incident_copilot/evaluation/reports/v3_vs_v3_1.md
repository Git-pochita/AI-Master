# V3 vs V3.1 Official Evaluation

## 1. 환경

- Azure OpenAI `gpt-4.1`
- endpoint: `https://skax.ai-talentlab.com`
- API version: `2024-12-01-preview`
- Ground Truth 30건 동일 (`evaluation/ground_truth.json`)
- 명령: `python3 evaluation/run_evaluation.py --versions v3_1`
- **1회 실행**. 실패 case 재실행 없음. 결과 보고 후 prompt/code 수정 없음

## 2. 기준 SHA

- evaluation base main: `75adc968467af04a1979f443c65f63241d7fbf37`
- freeze commit (runner isolation only): `c53bdd6f03723073faedad36bb21ff268b3ac462`
- V3 official baseline artifacts는 이 평가에서 덮어쓰지 않음

## 3. V3 baseline

출처: `evaluation/reports/v3_summary.json`, `v2_refined_vs_v3.md`

| KPI | V3 official |
| --- | --- |
| Final Diagnosis Accuracy | 93.3% (28/30) |
| Diagnosis Level | 100% |
| Owner | 100% |
| Net Corrected | 0 |
| Regression | 0 |
| Critic Revision Count | 1 |
| Critic Revision Precision | 0.0 |
| Unnecessary Revision Rate | 0.0 |
| F-02 / F-04 | Critic PASS, 미교정 |
| F-05 | false-positive REVISE, Gate가 변경 차단 |
| FAILED evidence misuse | 0 |

## 4. V3.1 결과

이번 run의 live V2 Producer → Critic.

| KPI | V3.1 |
| --- | --- |
| Final Diagnosis Accuracy | 93.3% (28/30) |
| Hypothesis Recall | 83.3% |
| Diagnosis Level Accuracy | 100% |
| Owner Accuracy | 100% |
| Required Tool Recall | 96.7% |
| Unnecessary Tool Rate | 10.0% |
| avg latency | 19.611초/건 |
| avg Tool calls | 1.067 |
| Tool failure count | 6 |
| failed_runs | 0 |
| Critic Revision Count | 0 |
| Critic Revision Precision | 0.0 |
| Unnecessary Revision Rate | 0.0 |
| Net Corrected | 0 |
| Regression | 0 |
| FAILED evidence misuse | 0 |

오답 2건은 F-02, F-04. 둘 다 이번 run의 V2 Producer도 `FILE_NOT_RECEIVED`였고 Critic은 PASS였다.

## 5. KPI comparison

Metric | V3 official | V3.1 | 비고
--- | --- | --- | ---
Final Diagnosis Accuracy | 93.3% (28/30) | 93.3% (28/30) | 동일. 오답 F-02/F-04
Hypothesis Recall | 83.3% | 83.3% | Producer 지표. miss 케이스 동일 (F-05, D-02, D-04, C-02, C-06)
Diagnosis Level Accuracy | 100% | 100% |
Owner Accuracy | 100% | 100% |
Required Tool Recall | 96.7% | 96.7% | Producer. C-03/C-04 0.5 동일
Unnecessary Tool Rate | 6.7% | 10.0% | Producer. V3.1만 C-05가 `validate_parameter` 1회 추가
avg latency | 20.201초 | 19.611초 | 로컬 측정. 운영 절감 아님
avg Tool calls | 1.033 | 1.067 | Producer. C-05 extra call
Tool failure count | 5 | 6 | Producer. C-05 FAILED 1건 추가
failed_runs | 0 | 0 |
Critic Revision Count | 1 | 0 | F-05가 V3.1에서 PASS
Critic Revision Precision | 0.0 | 0.0 | V3.1은 REVISE 0건
Unnecessary Revision Rate | 0.0 | 0.0 |
Net Corrected | 0 | 0 |
Regression | 0 | 0 |
FAILED evidence misuse | 0 | 0 |

Hypothesis Recall / Required Tool Recall / Unnecessary Tool Rate / Tool failure는 **이번 live V2 Producer** 지표다. Critic 효과와 구분한다.

## 6. F-02 상세

항목 | 값
--- | ---
original V2 cause | `FILE_NOT_RECEIVED`
expected | `INVALID_FILE_PATH`
structured comparison | conflict 1건 생성됨
potentially_conflicting | `same_directory_file:name=sales_20260901.csv,received=true,exact_name_match=false,date_token_overlap=true,filename_body_prefix_shared=true`
Critic verdict | PASS
issue types | 없음
related_evidence | 없음
recommended cause | null
Cause Revision Gate | 미적용 (PASS라 Revision 없음)
revised | false
final cause | `FILE_NOT_RECEIVED`
correct | false

입력에는 review 후보 sibling이 있었으나 Critic이 conflict로 승격하지 않았다.

## 7. F-04 상세

항목 | 값
--- | ---
original V2 cause | `FILE_NOT_RECEIVED`
expected | `INVALID_FILE_PATH`
structured comparison | conflict 1건 생성됨
potentially_conflicting | `same_directory_file:name=partner_20260901.csv,received=true,exact_name_match=false,date_token_overlap=true,filename_body_prefix_shared=true`
Critic verdict | PASS
issue types | 없음
related_evidence | 없음
recommended cause | null
Cause Revision Gate | 미적용
revised | false
final cause | `FILE_NOT_RECEIVED`
correct | false

F-02와 동일 패턴이다. Gate는 원인이 아니다.

## 8. F-05 상세

항목 | 값
--- | ---
original V2 cause | `INVALID_BUSINESS_DATE`
strong_causal | `parameter:name=business_date,value=20260831,expected=20260901,is_valid=false`
surface_symptoms | target missing + FileNotFound
potentially_conflicting | 없음 (날짜 토큰 미겹침)
Critic verdict | PASS
false-positive REVISE | **사라짐** (V3 official은 REVISE)
Gate | 미적용 (PASS)
final cause | `INVALID_BUSINESS_DATE`
correct | true

## 9. corrected cases

이번 V3.1 run 내부 (`original_v2_cause_code` → final):

- 없음. Net Corrected = 0

## 10. regression cases

이번 V3.1 run 내부:

- 없음. Regression = 0

대조군 F-01, F-03, F-06, P-05, P-06, C-01, C-06은 모두 PASS, V2 cause 유지, 정답.

## 11. Critic revision analysis

분류 | count | cases
--- | --- | ---
PASS + V2 correct | 28 | 대부분
PASS + V2 wrong | 2 | F-02, F-04
REVISE + unchanged | 0 | -
REVISE + corrected / regression / still wrong | 0 | -

V3 official의 F-05 REVISE는 이번 run에서 PASS로 바뀌었다. Revision 호출 0.

## 12. FAILED evidence safety

F-06 / P-06 / D-06 / S-06 / C-06:

- FAILED error는 최종 `evidence`에 없음
- `strong_causal_observations`에 없음
- diagnosis_level 과확정 없음 (해당 5건 중 SUCCESS 없는 F-06/P-06/D-06/S-06은 `추정`)
- Critic이 FAILED를 cause revision 근거로 쓰지 않음 (REVISE 0)

C-05는 이번 Producer가 불필요 `validate_parameter`를 호출해 FAILED 1건이 늘었으나, 최종 evidence에 그 error가 없고 level은 `추정`이다.

FAILED evidence misuse count = 0

## 13. stochastic V2 Producer 주의사항

V3 official 30건과 이번 V3.1 30건의 **final cause는 모두 같다**. 그래도 Producer 조사량은 완전히 같지 않다.

- C-05: V3 official은 tool 0회. 이번 V3.1 Producer는 `validate_parameter` FAILED 1회. 최종 cause는 둘 다 `FILE_NOT_RECEIVED` / `추정`
- Unnecessary Tool Rate 6.7% → 10.0%, tool failure 5 → 6 은 이 Producer 차이
- Hypothesis Recall miss 5건은 V3 official과 동일

Critic KPI(Revision Count, Precision, Net Corrected, Regression)만 Critic 효과로 해석한다.

## 14. 결론

- 이상적 성공(F-02/F-04 교정, Accuracy 100%)은 **달성하지 못했다**. 재실행하지 않았다.
- 최소 후보 중 Accuracy ≥ 96.7%와 Net Corrected ≥ 1은 미달. Regression 0, U=0, FAILED misuse 0, Level/Owner 100%는 충족.
- Structured Evidence Comparison은 F-02/F-04에 relevant sibling을 conflict 칸에 올렸다. 그래도 Critic은 기본 PASS를 유지했다. 병목은 “관찰 부재”가 아니라 **비교 결과를 REVISE로 올리지 않은 LLM Critic**이다.
- F-05 false-positive REVISE는 이번 run에서 제거되었다. Gate가 막을 일도 없었다.
- 기존 V3 official artifact는 보존되었다.

raw: `results/v3_1_critic/<case_id>.json`  
summary: `evaluation/reports/v3_1_summary.json`
