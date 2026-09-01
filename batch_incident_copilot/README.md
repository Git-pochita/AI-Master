# Batch Incident Copilot

배치 실행 로그를 분석하는 Agentic AI PoC입니다.

V0/V1/V2/V3는 별도 프로젝트가 아니라 같은 코드베이스의 개발 단계입니다.

- V0: 로그만 보고 단일 LLM이 진단
- V1: Function Tool Use (현재)
- V2: Dynamic Planning / Re-planning (미구현)
- V3: Critic / Reflection (미구현)

현재 평가 결과 및 다음 단계: [`docs/next_steps_v2.md`](docs/next_steps_v2.md)

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
python main.py --version v0 --log data/sample_logs/F-01.log --case-id F-01
```

기본값은 v0입니다. `--version`을 생략해도 V0로 동작합니다.

V1 Tool Use:

```bash
python main.py --version v1 --log data/sample_logs/F-01.log --case-id F-01
python main.py --version v1 --log data/sample_logs/D-01.log --case-id D-01
python main.py --version v1 --log data/sample_logs/S-01.log --case-id S-01
```

현재 V1 Tool:

- `check_file_status`
- `validate_parameter`
- `check_db_status`
- `check_sql_metadata`

모든 Tool은 로컬 mock JSON만 조회합니다. 실제 DB 접속과 credential 검증은 하지 않습니다.

- V0 결과: `results/v0_baseline/<case_id>.json`
- V1 결과: `results/v1_tool_use/<case_id>.json`

## 평가

단일 결과:

```bash
python evaluation/evaluator.py --result results/v0_baseline/F-01.json --case-id F-01
python evaluation/evaluator.py --result results/v1_tool_use/F-01.json --case-id F-01
```

30건 일괄 평가 (V0 + V1):

```bash
python evaluation/run_evaluation.py --versions v0 v1
```

지정 케이스만 실행:

```bash
python evaluation/run_evaluation.py --versions v0 v1 --case-id F-01 D-01 S-01
```

집계 리포트:

- `evaluation/reports/v0_summary.json`
- `evaluation/reports/v1_summary.json`
- `evaluation/reports/v0_vs_v1.md`

공식 평가셋은 `evaluation/ground_truth.json` 30건입니다. 위 리포트는 Azure OpenAI `gpt-4.1` 기준 공식 30건 V0/V1 결과입니다. 숫자 해석과 다음 단계는 [`docs/next_steps_v2.md`](docs/next_steps_v2.md)를 보십시오.

## Streamlit UI

```bash
cd batch_incident_copilot
streamlit run streamlit_app.py
```

브라우저에서 로그 파일을 업로드하거나 텍스트를 붙여넣은 뒤 V0 또는 V1을 선택하고 [분석 시작]을 누르면 됩니다. CLI는 그대로 사용할 수 있습니다.

## 테스트

```bash
cd batch_incident_copilot
pytest -q
```
