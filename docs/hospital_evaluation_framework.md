# 5장 평가 프레임워크 적용

## 적용 범위와 평가 독립성

`app/core/hospital_evaluation.py`는 병렬 엔진의 상태·이벤트를 읽기만 하는 사후 평가기다. LLM을 호출하지 않고 정책 결정과 상태를 변경하지 않는다. 단일 환자 엔진의 기존 평가기를 대체하지 않는다.

현재 병렬 demo 정책은 gold_label을 참조하고 일부 검사 결과를 합성한다. 따라서 보고서의 `validity.independent_clinical_evaluation`은 false다. 정확도 숫자가 산출되어도 독립적인 모델 성능이라고 해석하면 안 된다. 평가기를 분리한 것만으로 기존 정책의 정답 참조 문제가 해결되지는 않는다.

## 지표와 코드 연결

전 항목의 환자별 계산은 `evaluate_case()`, 그룹별 집계는 `evaluation_report()`에서 수행한다.

| PDF 항목 | 보고서 키 | 계산·적용 기준 |
|---|---|---|
| 5.3.1 Diagnosis Accuracy | outcome.diagnosis_accuracy | 완료 환자의 최종 진단과 gold_label.diagnosis 비교. 기존 diagnosis_catalog 정규화와 명시 diagnosis_aliases 사용. 부분 문자열·LLM 추측 비교 없음 |
| 5.3.2 Department Accuracy | outcome.department_accuracy | 최종 선택 진료과와 gold_label.department를 공통 department catalog로 정규화하여 비교. 최초 의뢰만의 정확도는 아님 |
| 5.3.3 NTCR | process.ntcr | Σ(필수 검사 집합 ∩ 완료 검사 집합 크기) / Σ필수 검사 수. 환자별 비율의 단순 평균 아님 |
| 5.3.4 UTI | process.uti | 권고되지 않은 완료 검사 이벤트 수 / Σ필수 Perform 검사 수. considered_tests는 불필요 검사에서 제외. 1을 초과할 수 있음 |
| 5.3.5 UCR | process.ucr | 허용 진료과 외 실제 consult_started 이벤트 수 / 전체 실제 consult_started 수. 의뢰만 하고 시작되지 않은 협진은 제외. 0회면 N/A |
| 5.3.6 CAMR | safety.camr | 최종 확정 전에 관측되지 않은 사전 지정 중요 행동 수 / 지정 중요 행동 수. 선택적 도착 후 deadline 적용 |
| 5.3.7 APL | efficiency.apl | 환자별 기록된 임상 행동 수의 평균. 질문·검사 의뢰·결과 검토·협진 의뢰·재평가·최종 확정 포함 |
| 5.3.8 TTD | efficiency.ttd | 최종 진단 시각 − 도착 시각. mean/median/Q1/Q3/IQR 제공 |
| 5.3.9 MWT | multi_patient.mwt | 최초 ER 평가 시각 − 도착 시각. 큐 누적 대기시간과는 다름 |
| 5.3.10 CPWT | multi_patient.cpwt | 독립 critical_patient=true 하위 집합의 최초 평가 대기 |
| 5.3.11 DBER | multi_patient.dber | 최초 평가보다 엄격히 이른 악화가 있었던 환자 수 / 독립 deterioration_at_risk=true 환자 수. 명시 악화 모델 필요 |

시간·행동 수 분포의 사분위수는 정렬 표본의 `(n−1)p` 위치에서 선형 보간한다. 표본 1개이면 IQR=0, 표본 0개이면 null이다.

운영 정의:

- NTCR의 P는 `completed_tests`, UTI의 수행 건수는 `result_received` 이벤트다. 시작 후 취소된 검사는 완료 검사에 포함하지 않는다. 취소로 소비된 자원은 6장 이용률에 남는다.
- 필수/권고 검사명은 대소문자·구두점 정규화 및 명시 test_aliases로 맞춘다. 동일 필수 검사는 집합으로 중복 제거하며, UTI의 반복 완료는 이벤트마다 센다.
- APL은 큐 이동·배정·장비 반환·결과 도착 같은 자동 이벤트를 제외한다. 검사 묶음 1회 의뢰는 1개 행동이다. 기존 `review_results`는 자동 복귀 과정에서 기록되는 의미적 검토 행동이므로 실제 사람의 인지 작업 수를 측정하는 것은 아니다.
- CAMR은 annotation의 event_type/action/target을 정확히 매칭한다. target은 검사명·진료과·질문 텍스트를 사용한다. 동일 시각이면 이벤트 기록 순서로 최종 확정 이전을 구분한다. 서로 다른 요구조건이 동일 이벤트로 충족될 수 있으며 반복 횟수 요구는 현재 지원하지 않는다.
- DBER의 분모를 baseline risk나 ESI로 추정하지 않는다. 악화와 최초 평가가 같은 분이면 '평가 이전'으로 세지 않는다.

## 데이터 부족·미완료 처리

각 집계 항목은 `value`, `observed_value`, `status`, `included_cases`, `total_cases`, `excluded`, `numerator`, `denominator`를 제공한다. 분포 지표는 `observed_distribution`도 제공한다.

- 필요한 라벨이 빠지거나 적용 대상 환자가 아직 종료/평가되지 않았으면 전체 `value=null`, `status=missing_or_censored`다.
- 이때 `observed_value`는 평가 가능한 부분집합의 값이다. 전체 코호트 점수처럼 비교하면 안 된다.
- 분모가 0이면 `not_applicable`이며 0점으로 채우지 않는다.
- 불필요 협진 0회와 전체 협진 0회는 다르다. 후자는 N/A다.
- APL/UCR/CAMR/UTI는 시작·종료 이벤트가 확인된 완료 기록에서만 집계한다. 시작·종료가 있다고 중간 로그의 완전성이 증명되는 것은 아니다.
- 임의 가중치의 단일 종합점수는 만들지 않는다. 낮은 APL·TTD만으로 정책이 더 좋다고 결론 내리지 않는다.

## 정답 워크플로 입력

환자 case의 `evaluation`에 전문가가 사전에 정한 평가 기준을 넣는다. 아래는 **형식 설명용 가상 예시**이며 실제 환자에 자동 적용하지 않는다.

```json
{
  "evaluation": {
    "critical_patient": true,
    "deterioration_at_risk": true,
    "diagnosis_aliases": ["허용할 진단명 별칭"],
    "workflow": {
      "required_tests": ["CBC"],
      "considered_tests": ["Chest CT"],
      "test_aliases": {"Complete Blood Count": "CBC"},
      "acceptable_consultations": ["internal_medicine"],
      "critical_actions": [
        {
          "id": "required_cbc_result",
          "event_type": "result_received",
          "target": "CBC",
          "deadline_min": 30
        }
      ]
    }
  }
}
```

빈 리스트는 '없음이 확인됨', 키 누락은 '기준 미제공'이다. `considered_tests`는 없다고 판단했더라도 명시적으로 `[]`를 입력해야 UTI를 계산한다. 부울 라벨은 문자열이 아닌 true/false여야 한다. critical_actions의 event_type은 `event_schema.EventType`에 등록된 사건이어야 한다. 현재 기록되지 않는 신체검사·red flag 확인은 임의로 충족 판단하지 않고 먼저 이벤트 계측을 추가해야 한다.

운영용 추천 검사(`recommended_tests`, `meta.demo.decisive_tests`)를 평가용 required_tests로 복사하지 않는다. 데이터 규격 검증은 초기화 시 `validate_evaluation()`으로 수행한다.

## 실행과 결과물

병렬 live 실행의 종료 시:

- `hospital_evaluation_metrics.json`을 별도로 저장한다.
- `parallel_live_run_summary.json`의 `evaluation_metrics`에 포함한다.
- preview runner와 저장되는 what-if 분기 결과에도 동일 평가기를 적용한다.
- 웹 화면에 별도 평가 대시보드를 추가한 것은 아니다.

기존 실행은 재시뮬레이션 없이 평가할 수 있다.

```powershell
python -m app.scripts.evaluate_parallel_run --report outputs/reports/20260916_093813/parallel_live_run_summary.json --output outputs/reports/chapter5_evaluation/hospital_evaluation_metrics.json
```

외부 annotation 파일은 `{ "case_id": { "critical_patient": true, "workflow": { ... } } }` 형태로 `--annotations path.json`에 전달한다. 평가할 때만 병합하며 원본 보고서는 수정하지 않는다. 사후 입력을 지원한다고 해서 사후에 정답 기준을 결과에 맞게 조정해도 된다는 뜻은 아니다. 비교 전에 전문가가 기준을 고정해야 한다.

## 동일 환자 비교 — 5.4

`paired_comparison(left, right)` 또는 CLI `--compare-report 다른실행.json`으로 환자별 right−left 차이를 계산한다. 양쪽 환자 집합, 환자 데이터·도착 시각·annotation의 SHA-256 서명, 지표 정의가 같아야 한다. 값이 없는 환자는 제외 목록을 기록한다.

이는 환자별 차이의 분포다. 비율의 전체 micro 집계 차이와 동일하지 않을 수 있고, 통계적 유의성 검정이나 인과효과 추정은 제공하지 않는다. 동일 case라는 이유만으로 seed·용량·정책 등 실험 조건 통제가 보장되지 않으므로 비교 설계는 별도로 고정해야 한다.

## 검증 결과와 남은 일

- 전체 테스트 41개 통과. 5장 테스트는 11개 지표의 수치 예제, 별칭, UTI 분모·반복 검사, deadline, 0분모, 미완료, 누락 라벨, 읽기 전용 평가, 동일 case 비교, 실제 scheduler 통합을 포함한다.
- 기존 5명 실행 재평가: APL 5회, TTD 평균 37.8분, MWT 평균 4.4분. 진단/진료과 일치율은 각각 1.0이지만 **정답 참조 demo 결과이며 독립 정확도가 아니다**.
- 정답 workflow와 독립 라벨이 없어 NTCR/UTI/UCR/CAMR/CPWT/DBER는 null과 누락 이유를 출력했다.
- 실제 사용 전 필요한 것: 전문가가 고정한 정답 workflow, critical/at-risk 라벨, 임상 악화 모델, 필요한 임상 행동 이벤트 계측, 정답을 보지 않는 정책과 실제 검사결과 계약.
