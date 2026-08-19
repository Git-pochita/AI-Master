# Batch Incident Copilot

배치 실행 로그를 분석하는 Agentic AI PoC입니다.

V0/V1/V2/V3는 별도 프로젝트가 아니라 같은 코드베이스의 개발 단계입니다.

- V0: 로그만 보고 단일 LLM이 진단
- V1: Function Tool Use (현재 추가)
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

위치: `batch_incident_copilot/.env`

```bash
cp .env.example .env
```

API Key는 코드에 넣지 않습니다.

## 실행

V0 Baseline:

```bash
python main.py --version v0 --log data/sample_logs/file_case_001.log --case-id file_case_001
```

기본값은 v0입니다. `--version`을 생략해도 V0로 동작합니다.

V1 Tool Use:

```bash
python main.py --version v1 --log data/sample_logs/file_case_001.log --case-id file_case_001
```

- V0 결과: `results/v0_baseline/file_case_001.json`
- V1 결과: `results/v1_tool_use/file_case_001.json`

## 평가

```bash
python evaluation/evaluator.py --result results/v0_baseline/file_case_001.json --case-id file_case_001
python evaluation/evaluator.py --result results/v1_tool_use/file_case_001.json --case-id file_case_001
```

비교 항목:

- `final_diagnosis_correct`
- `hypothesis_recall_hit` (초기 hypotheses에 실제 원인이 있는가)
- `diagnosis_level_correct`
- `owner_correct`

V1 Tool은 로컬 mock JSON만 조회합니다. 실제 파일 시스템/DB는 사용하지 않습니다.

## 테스트

```bash
cd batch_incident_copilot
pytest -q
```
