# Batch Incident Copilot — V0 Baseline

배치 실행 로그를 단일 LLM으로 진단하는 Baseline PoC입니다.

V0/V1/V2/V3는 별도 프로젝트가 아니라 같은 코드베이스의 개발 단계입니다.  
현재 구현 범위는 **V0 Baseline만**입니다.

- V0: 로그만 보고 단일 LLM이 진단 (현재)
- V1: Function Tool (미구현)
- V2: Dynamic Planning / Re-planning (미구현)
- V3: Critic / Reflection (미구현)

## 요구 사항

- Python 3.10+
- Azure OpenAI 호환 엔드포인트 접근 권한

## 설치

```bash
cd batch_incident_copilot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 환경 변수

프로젝트 디렉터리에 `.env`를 만듭니다.

위치: `batch_incident_copilot/.env`

```bash
cp .env.example .env
```

`.env` 내용:

```
AZURE_OPENAI_ENDPOINT=https://skax.ai-talentlab.com
AZURE_OPENAI_API_KEY=실제_키
AZURE_OPENAI_API_VERSION=2024-12-01-preview
AZURE_OPENAI_MODEL=gpt-4.1
```

API Key는 코드에 넣지 않습니다.

## 실행

```bash
cd batch_incident_copilot
python main.py --log data/sample_logs/file_case_001.log --case-id file_case_001
```

- 콘솔에 진단 JSON이 출력됩니다.
- 같은 내용이 `results/v0_baseline/file_case_001.json`에 저장됩니다.
- Input Validation이 ABORT이면 종료 코드 1로 중단합니다.
- WARN이면 stderr에 경고를 출력하고 진단을 계속합니다.

## 평가

Ground Truth는 `evaluation/ground_truth.json`의 `file_case_001` 1건만 준비되어 있습니다.

```bash
python evaluation/evaluator.py --result results/v0_baseline/file_case_001.json --case-id file_case_001
```

비교 항목:

- `final_diagnosis_correct`
- `hypothesis_recall_hit`
- `diagnosis_level_correct`
- `owner_correct`

V0는 Tool이 없으므로 `INVALID_BUSINESS_DATE`를 최종 원인으로 확정하지 못할 수 있습니다. 이는 예상된 Baseline 한계입니다.

## 테스트

```bash
cd batch_incident_copilot
pytest -q
```

## 폴더 구조

```
batch_incident_copilot/
├── main.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── app/
│   ├── baseline.py
│   ├── llm_client.py
│   ├── schemas.py
│   └── input_validator.py
├── config/
│   └── settings.py
├── prompts/
│   └── v0_system_prompt.txt
├── data/sample_logs/
│   └── file_case_001.log
├── evaluation/
│   ├── ground_truth.json
│   └── evaluator.py
├── results/v0_baseline/
└── tests/
    └── test_input_validator.py
```
