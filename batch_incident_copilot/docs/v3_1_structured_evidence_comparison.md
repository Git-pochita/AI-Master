# V3.1 Structured Evidence Comparison

상태: **구현**. 공식 30건 live 평가는 이 문서 작성 시점에 실행하지 않는다.

기준 main: `62c3fcf3afbb8594bb0993bbba3f57756d1244f0`  
근거: [`v3_official_error_analysis.md`](v3_official_error_analysis.md)

기존 V3 official artifact(`evaluation/reports/v3_summary.json`, `results/v3_critic/*.json`)는 덮어쓰지 않는다.

## 무엇을 바꿨나

V2 결과는 그대로 두고, Critic 입력 앞에 **관찰 가능한 SUCCESS 필드 정규화**를 둔다.

```text
V2 result
→ observable evidence normalization
→ Structured Evidence Comparison
→ Critic (1회)
→ 기존 Cause Revision Gate
→ 필요 시 Revision 1회
```

결정적 레이어는 원인 코드를 고르지 않는다. `same_directory_files → INVALID_FILE_PATH` 규칙은 없다.

File Tool의 `potentially_conflicting_observations`는 received sibling 전부가 아니다. 같은 디렉터리 + received=true만으로는 conflict로 올리지 않는다. 요청 파일과 sibling이 아래 **관찰 가능한 관계**를 모두 가질 때만 review 후보다.

- 날짜 토큰 겹침: 파일명 날짜 또는 extracted_info의 `business_date`/`job_run_date`
- 파일명 body prefix 공유: 확장자·8자리 날짜를 뺀 body가 서로 접두어를 공유

이 관계가 없으면 received sibling은 supporting observation으로만 남긴다. edit-distance 임계값이나 cause 확정 규칙은 쓰지 않는다.

## 모듈

- `app/evidence_comparison.py`: `StructuredObservation`, `EvidenceComparison`, `build_evidence_comparison()`
- `app/critic.py`: `build_critic_input()`에 `evidence_comparison` 추가. Gate 의미는 유지
- `prompts/v3_critic_prompt.txt`: coverage / contradiction review / causal hierarchy / alternative

## 하지 않은 것

- V2 planning / V2 prompt / GT / evaluator / cause vocabulary 변경
- 추가 Tool, case_id 분기, official 30-case 평가
