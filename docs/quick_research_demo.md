# 7·9·10 빠른 데모

## 실행

기존 프로젝트 Python 환경에서 루트 디렉터리를 열고 실행합니다. Ollama 서버, API 키, 모델 다운로드는 필요 없습니다. 프로젝트 의존성이 없는 새 환경에서는 먼저 `python -m pip install -r requirements.txt`로 준비합니다.

```powershell
python -m app.scripts.run_research_demo
```

기본 결과 폴더는 `outputs/research_demo/<UTC 시각>/`입니다. 원하는 **새 폴더**를 지정할 수도 있습니다. 기존 폴더는 덮어쓰지 않습니다.

```powershell
python -m app.scripts.run_research_demo --output-dir outputs/research_demo/manual_01
```

성공하면 종료 코드 0, 실패하면 1입니다. 예상 경로에서 벗어나 LLM 호출이 필요해지면 외부 요청 없이 실패합니다. 저장된 보고서와 방문 단위 checkpoint로 원인을 확인합니다. 이 데모 명령 자체의 자동 재개는 없으며 기존 장기 기억 실행기의 재개 기능과 별개입니다.

## 무엇을 실행하는가

| 장 | 실행 범위 | 제외된 검증 |
|---|---|---|
| 7 | 이전 방문 기억을 실제 엔진에 제공하고 VoI 선택 전에는 비공개로 유지, 선택 후 노출 | 실제 임베딩 생성, 자연어 충돌 성능, 자유로운 다회 방문 LLM 대화 |
| 9 | 저장된 실제 LLM 전문과 응답에서 효용 재학습, 별도 환자 응답으로 라우팅·regret 재평가 | 새 전문과 호출, 이번 방문과의 협진 통합 실험 |
| 10 | 실제 스케줄러에서 확률 갱신·행동 선택·객관적 증거에 의한 조기 종료 | 실제 임상 확률 보정, VoI 없는 LLM 기준선과의 비교 |

7·10의 입력은 `app/data/voi_synthetic/`, 9의 입력은 `app/data/research_synthetic_v1/`입니다. 모두 합성·미검수 연구 자료입니다. 환자/의사/전문과가 새 LLM 대화를 생성하는 데모가 아니라, 짧게 구조를 확인하는 오프라인 데모입니다.

## 비교 조건

각 조건에서 같은 두 환자 방문을 실행합니다. 진단 후보는 Synthetic A/B입니다.

1. `cheap_test`: 기존 모형 + 기억 허용. 검사 → 진단.
2. `costly_test_no_memory`: 검사 비용 0.4, 문진/협진 비용 1.0으로 변경 + 기억 차단. 검사 → 진단.
3. `costly_test_with_memory`: 2와 같은 비용 모형 + 기억 허용. 기억 조회 → 검사 → 진단.

비용은 임상 가격이 아닌 합성 효용 단위입니다. 기억 비용은 0.01입니다. 2와 3은 기억 사용 여부만 다르지만, 1과 2는 여러 행동 비용을 함께 변경합니다. 이를 검사 가격 하나의 인과 효과로 해석하지 않습니다. 기억이 선택되어도 객관적 증거 없는 조기 확진을 허용하지 않으므로 검사 수는 줄지 않습니다.

## 결과 확인

- `report.md`: 비교 표와 해석.
- `summary.json`: 조건별 집계, 행동 순서·근거·기억 ID, 입력 파일 SHA256, 실행 시간.
- `<조건>.model.json`: 실행한 확률·비용 모형.
- `<조건>.report.json`: 원본 엔진 결과와 VoI 후보별 점수·사후 확률.
- `<조건>.evaluation.json`: 정확도, Brier, log loss, 호출·검사 수.
- `<조건>.checkpoint.json`: 방문 완료 시점 상태.
- `routing.utility.json`, `routing.decisions.json`, `routing.evaluation.json`: 재학습 모형, 선택, 전문과별 점수·이유·regret.

정상 기대값: 조건별 2개 방문 완료, 정확도 1.0, 새 LLM 호출 0, 검사 2회. 모형 비용 합계는 순서대로 0.10 / 0.80 / 0.82입니다. 이는 설계된 두 사례의 동작 확인이며 임상 정확도나 기억의 성능 개선을 입증하지 않습니다.

## 이후 실험

1. 위 명령으로 자신의 환경에서 실행하고 `report.md`와 결정 근거 확인.
2. [VoI 안내](voi_research.md)의 실제 LLM 기준선 및 비교 명령 실행. 이 단계는 Ollama와 모델이 필요하며 호출 시간·비용이 발생할 수 있습니다.
3. [7·9번 안내](research_7_9_completion.md)에 따라 새로운 전문과 응답 수집 후 환자 분리 평가.
4. 검수된 데이터와 충분한 표본을 확보한 뒤 성능·비용에 대한 연구 결론 도출.

선택적인 최소 수식 검사는 `python -m unittest discover -s tests -p test_voi_minimal.py`입니다. 데모 내부에는 완료 여부, 예상 행동 순서, 정확도, 0회 호출, 라우팅 평가 coverage에 대한 검사가 포함되어 있습니다.
