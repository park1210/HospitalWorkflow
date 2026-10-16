# 6장 병원 자원·환자 흐름 모델 적용

최신 구조 변경: [장비 점유·결과 대기 분리 및 필요한 데이터](hospital_flow_structure_review.md). 테스트 29개 통과. 명시적 `test_occupancy`가 있으면 turnaround와 별도로 장비 반환을 처리하며, 없을 때만 기존 전체 점유 가정을 사용한다.

추가 적용: [수학적 계약·조건부 논증·실행 중 보존 검사](hospital_flow_mathematical_contract.md). 현재 테스트는 23개이며 72개 설정 조합을 포함한다. 보고서에 `conservation`, `progress`, `demand_analysis`가 추가되었다. 아래 15개 테스트 기록은 최초 적용 시점의 결과다.

## 범위

`HospitalParallelScheduler`에 적용했다. 단일 환자 `simulator.py`와 별도 순차 시뮬레이터의 정책은 그대로다. 추가 LLM 호출은 없다. 이번 변경은 흐름의 일관성과 측정 가능성을 개선하며, 임상 정확도나 실제 병원 성능의 검증을 의미하지 않는다.

| 항목 | 구현 | 적용 범위와 조건 |
|---|---|---|
| 6.1 상태 전이 | 적용 | 완료 이벤트 처리 → 자원 반환 → 도착 → 악화/우선순위 → 배정 → 구간 적분. 매 단계 큐와 자원 소유권 검사 |
| 6.2 도착 | 적용 | 고정 시각 또는 고정 seed의 지수 도착 간격. 주어진 환자 수만 생성하며 무한 도착 과정은 아님 |
| 6.3 도착률·서비스율·부하 | 일부 | 큐별 방문률, 자원별 예약시간/예약 횟수, `offered_load(λ, E[S], c)=λE[S]/c`. 관측된 배정 횟수를 외생 수요로 오인하지 않도록 구분 |
| 6.4 우선순위 M/M/1 | 참고 계산 | `mm1_priority_reference`만 제공. Poisson 도착·공통 지수 서비스·서버 1개·고정 비선점 우선순위·정상상태·총 부하 < 1 조건. 다중 자원과 동적 우선순위가 있는 본 엔진의 예측식으로 쓰지 않음 |
| 6.5 Little 법칙 | 적용 | 큐별 면적 적분과 완료/미완료 방문 대기시간 합의 보존 검사. 유한 구간의 정확한 회계 검증이며 정상상태 추정이 아님 |
| 6.6 용량 제약 | 적용 | 실제 자원 단위별 소유자 1명, 중복 예약/잘못된 이벤트 실패 처리. 의사 복수 배정, 검사 슬롯 재사용 |
| 6.7 이용률 | 적용 | 개별 busy/T, 그룹 Σbusy/(cT). 이동·예약 시간이 포함되며 순수 진료 생산성과는 다름 |
| 6.8 동적 우선순위 | 적용 | `w_s(6−ESI) + w_w×누적 큐 대기 + w_r×위험도`. ESI 1 또는 Critical은 우선 보호, 동점은 도착 순서. 비선점 |
| 6.9 건강 상태 | 일부 | 명시된 시간 임계값으로 Stable → Worsening → Critical. 임계값 누락 시 전이를 생성하지 않고 데이터 부족 표시. 회복/처치 반응은 미구현 |
| 6.10 WTE | 조건부 | `1−CPWT/MWT`. 대기는 도착부터 최초 ER 평가 시작까지. 전원 독립 라벨과 최초 평가가 있고 분모가 양수일 때만 계산 |

## 시간과 회계 규칙

- 시간 단위는 분, 양의 소요시간과 도착시간은 분 경계로 올림한다.
- `queue_wait_minutes`는 triage/bed/ER/test/specialty 큐에 실제 머문 구간만 누적한다. 진료·검사·협진 서비스시간을 대기에 더하지 않는다. 침상 배정 후 기존 1분 이동 대기는 ER 큐에 포함된다.
- `first_evaluation_min`은 최초 실제 ER 평가 시작이며 재진에서 덮어쓰지 않는다. `final_diagnosis_min`은 종료 시각이다.
- ER 문진·검사 의뢰 이후 다음 큐 진입은 설정된 평가시간 종료까지 지연한다. 최종 확정은 기존 정책처럼 판단 순간 종료하므로 마지막 평가의 전체 예약시간을 소비하지 않는다.
- 검사시간은 환자 `resource_profile.test_turnaround[검사명]`을 우선하고, 없으면 설정값을 쓴다. 결과 반환과 자원 반환은 새 배정보다 먼저 처리한다.
- 종료 시각에 미완료 환자가 있으면 `termination=incomplete`, 뷰어는 `stopped`다. 완료로 표시하거나 숨겨진 추가 시간을 진행하지 않는다.
- Little 검사: `∫Q(t)dt − (완료 방문 대기 합 + 열린 방문의 현재까지 대기 합) = 0`. 각 큐의 경계를 별도로 유지한다.
- 스냅샷에 설정·적분값·첫 평가시각을 저장한다. 구형 스냅샷은 복원 시점부터 회계하며 `partial_accounting_window`를 표시한다. 과거 대기량을 복원한 것으로 해석하지 않는다.
- what-if는 최초 ER 평가 이후만 허용한다. 진행 중 검사와 충돌하는 새 행동은 오류로 반환하고, 즉시 확정은 남은 이벤트·예약을 취소한다. 자원 대기만으로 분기를 조기 종료하지 않는다.

## 실행

기본 설정으로 기존 5명 시나리오 및 보고서 생성:

```powershell
$env:LIVE_VIS_STEP_DELAY_SEC='0'
python -m app.scripts.run_live_parallel_visual_multi_patient --fixed-demo --minute-limit 180 --min-demo-minutes 0
```

설정 예시(ER 의사 2명, 평가시간 2분):

```powershell
python -m app.scripts.run_live_parallel_visual_multi_patient --fixed-demo --flow-config app/data/hospital_flow_config.example.json --minute-limit 180
```

`run_live_parallel_web_session`에도 `--flow-config`를 전달할 수 있다. 기본 설정은 `app/core/hospital_flow.py`의 `DEFAULT_FLOW_CONFIG`에 있다. 용량 0은 부족 상황 실험을 위해 허용한다. 침상은 현재 장면의 4개까지만 허용한다. 추가 의사/간호사/검사 슬롯은 기존 위치를 공유하는 논리 자원이다.

결과 위치 `outputs/reports/<run_id>/`:

- `hospital_flow_metrics.json`: 큐 회계, 이용률, 최초 진료 대기, WTE, 미완료 목록, 데이터 부족.
- `parallel_live_run_summary.json`: 원본 환자, 설정, 스냅샷과 흐름 지표.
- 기존 live visual state/history 및 웹 뷰어 파일.

Poisson 실험은 `arrival.mode="poisson"`, `rate_per_minute`, `seed`를 설정한다. seed 고정은 재현성을 제공하며, 분 단위 올림과 유한 환자 수 때문에 이상적인 연속시간 Poisson 관측과 정확히 같지는 않다.

## 필요한 데이터 — 우선 확보할 항목

1. **환자 도착·각 큐 진입·서비스 시작/끝·퇴실 시각**: 시간대별 λ와 서비스시간 분포, 실제 대기시간 검증에 필요하다.
2. **자원별 실제 점유시간과 근무표**: 검사 결과 대기시간 전체와 장비 점유시간은 다르다. 현재는 turnaround 전체를 슬롯 점유로 취급한다. 의사·간호사·CT·MRI별 동시 처리량과 교대 근무 정보가 필요하다.
3. **악화 임계값과 적용 시계**: 도착 후 경과시간인지 순수 대기 누적인지 구분하고 임상적으로 검토한 값을 제공해야 한다. 현재 데이터의 baseline risk만으로 3단계 임계값을 추정하지 않는다.
4. **처치·회복 모델**: 처치 종류, 시각, 상태 변화와 확률/규칙이 있어야 회복·악화 억제를 모델링할 수 있다.
5. **독립적인 critical_patient 라벨**: `evaluation.critical_patient`에 boolean을 제공한다. 시스템이 산출한 ESI나 정답 진단명을 대신 쓰지 않는다. 라벨 부족·미진료·중증 표본 없음·평균 대기 0에서는 WTE가 null이다.

임계값 스키마 예시(아래 숫자는 **테스트용 가상 값**, 임상 권장값 아님):

```json
{
  "temporal_profile": {
    "arrival_time_min": 0,
    "flow_deterioration": {
      "clock": "queue_wait",
      "worsening_after_min": 20,
      "critical_after_min": 40
    }
  },
  "evaluation": {"critical_patient": true}
}
```

`clock`은 `since_arrival` 또는 `queue_wait`. 임계값 없는 환자의 `Stable`은 초기 모델 상태일 뿐 임상적 안정 확인이 아니다. 보고서의 `missing_deterioration_thresholds`와 함께 해석한다.

## 구조적으로 남은 한계

- 병렬 엔진의 기존 demo clinical policy가 `gold_label`을 이용한다. 독립적인 진단 정확도 실험 전에 정답 분리와 관측 가능한 증거 기반 정책이 필요하다.
- CT/MRI 등은 하나의 imaging pool을 공유한다. 장비별 자원 분리와 복수 자원 동시 획득 모델이 필요하다.
- 간호 인력 제약은 triage에만 적용한다. 일반 처치·관찰 간호 부하는 아직 없다.
- 위험도 0/0.5/1 매핑과 우선순위 기본 가중치는 설계값이며 임상 보정값이 아니다.
- 진단 확정 시 침상을 반환한다. 입원 대기, 퇴실 준비, 청소시간은 별도 모델이 필요하다.
- 고정된 서비스시간과 고정 근무 용량만 지원한다. 교대·고장·확률적 소요시간·회복은 추가 확장 대상이다.
- 기존 전문과 자원이 없는 의뢰는 지연될 수 있다. 미완료 결과를 성공으로 해석하면 안 된다.

## 검증

```powershell
python -m unittest discover -s tests -v
```

인공 환자로 중복 자원 배정, 다중 의사, 대기/서비스 분리, 실제 turnaround, 용량 0, 유한 구간 보존, 명시적 악화, 스냅샷 재개와 격리, what-if 취소, WTE 분모/라벨, M/M/1 안정 조건을 검사한다. LLM 호출 없이 실행한다.

2026-09-16 검증 결과:

- 회귀 테스트 15개 통과, 변경한 Python 파일 구문 검사 통과.
- 기본 5명 시나리오: 73분에 5명 완료, 평균 최초 평가 대기 4.4분, 모든 큐 보존 오차 0. 임계값/독립 중증 라벨 부족을 보고하고 WTE는 null.
- 결과: `outputs/reports/20260916_093813/hospital_flow_metrics.json` 및 웹 뷰어 생성 확인.
- 영상 슬롯 0 실험: 180분에 P05 미완료, 모든 큐 보존 오차 0. `imaging_shortage_flow_metrics.json`에 별도 저장.
- 구형 `20260618_234002` 실행의 중간 스냅샷 복원 후 전원 완료 확인. 모든 과거 스냅샷의 호환성을 보장하는 검사는 아님.
