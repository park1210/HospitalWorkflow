# Action replay B3/B4: 실행 준비 및 제한

## 결과

사용할 준비 결과는 `outputs/action_replay_study_v2/`다. `action_replay_study_v1`은 개발 중 생성한 초기 출력이므로 사용하지 않는다. 원본 데이터는 변경하지 않았다.

- 학습: **66명**, 평가: **26명**, 제외: **8명**. 환자는 겹치지 않는다.
- 제외 내역: 복수/누락 라벨 3명, 명확한 숫자 검사 없음 3명, 표본 부족/라벨 그룹 충돌 2명. 사례별 사유는 `study_report.json`에 있다.
- 진단 범주 15개, registry 전문과 5개. 기존 shared Qwen registry를 필요한 과로 제한했다. 서로 다른 LoRA 모델을 새로 만든 것이 아니다.
- B4 모델 생성 완료: train-only 빈도 + Dirichlet alpha=1, train-only median 이진 구간, horizon=2. **미검수·탐색용 통계 모델**이다.
- B3 수집 입력 생성 완료: 66개의 같은 관측 probe를 전문과 5개에 제공하므로 **실제 호출 예정 330회**. 아직 LLM 수집과 B3 모델 학습은 실행하지 않았다.
- 모든 비교 조건은 같은 평가 26명, 제한된 행동 후보, 모델 binding, Memory budget을 사용한다.

## 변경 파일

| 파일 | 변경 |
|---|---|
| `app/scripts/prepare_action_replay_study.py` | 환자 분리, 명시적 제외, 검사 code/unit 정규화, train-only 행동 선정·구간화·VoI 추정, Routing probe 및 실험 plan 생성 |
| `app/core/information_outcomes.py` | `replay_bins_v1`로 명시된 모델만 공개 결과의 구간 ID를 인식. 원본 JSON은 evidence에 보존 |
| `app/scripts/run_paper_experiments.py` | B3/B4에 실제 `primary_router=adaptive` 전달, plan의 Memory budget 적용 |
| `app/core/paper_evaluation.py` | encounter의 VoI 행동을 LLM audit과 planning trace에서 두 번 집계하던 문제 수정 |
| `app/core/longitudinal_memory.py` | memory ID 중복/대체 기록 조회를 인덱스로 처리. 순서·검색 점수·시간 필터는 유지. 큰 기록 집합의 반복 선형 검색 제거 |
| `tests/test_action_replay_study.py` | 분리·학습값 불변성·관측 후 갱신·실제 Runner B4·행동 중복 집계 방지 검증 |

## 실행 명령 (프로젝트 루트, 순서대로)

### 1. 실제 전문과 응답 수집

Ollama에서 `qwen2.5:1.5b-instruct`를 사용할 수 있어야 한다. 아래 명령은 330회 호출할 수 있다. 파일이 이미 존재하면 새 이름을 사용한다.

```powershell
python -m app.scripts.collect_routing_outcomes --probes outputs/action_replay_study_v2/routing_probes.json --registry outputs/action_replay_study_v2/registry.json --prices outputs/action_replay_study_v2/prices.json --output outputs/action_replay_study_v2/routing_train.json
```

source-observed 진단 라벨은 scoring에만 사용되며 prompt에 넣지 않는다. 이 수집은 초기 상태의 단일 진단 probe 성능이며 전체 방문 성공률은 아니다. 동일 base model이어도 specialty role에 따라 실제 답이 다를 수 있지만, 유의한 차이가 난다고 보장하지 않는다.

### 2. 실제 응답으로 Routing artifact 생성

```powershell
python -m app.scripts.build_research_models --evaluation-cases outputs/action_replay_study_v2/cases.json --registry outputs/action_replay_study_v2/registry.json --routing-data outputs/action_replay_study_v2/routing_train.json --output-dir outputs/action_replay_study_v2/fitted
```

실패 응답은 진단 오답으로 학습하지 않는다. 실패가 있으면 학습기가 명시적으로 중단한다. 해당 실패 응답을 재수집해야 한다. 데이터가 없는 전문과에 임의의 성공률을 부여하지 않는다.

### 3. 모델 호출 없는 설정 검증

```powershell
python -m app.scripts.run_paper_experiments --plan outputs/action_replay_study_v2/plan.json --conditions B3 B4
```

### 4. 실제 B3/B4 실행

```powershell
python -m app.scripts.run_paper_experiments --plan outputs/action_replay_study_v2/plan.json --conditions B3 B4 --execute --repeats 1 --output-dir outputs/action_replay_B3_B4_r1
```

B0~B4 모두 실행하려면 `--conditions B0 B1 B2 B3 B4`로 바꾼다. 이 plan의 baseline은 **기존 ER-only**이며 Rule baseline과 동일하다고 간주하지 않는다. B1은 30,000자 budgeted full history다. baseline 선택은 결과 보고 시 반드시 명시한다.

## 행동 공간 및 확률 가정

원본 4,399개 Test target에는 사례별 고유 문자열이 포함된다. 이를 원본 코드와 단위로 연결한다. 평가 진단이나 숨겨진 평가 결과를 이용해 행동을 고르지 않는다.

기본 최대 6개 행동은 모든 학습 진단에 실제 관측이 있는 후보 중 **학습 사례에서의 출현 수**로 선택한다. 동률은 코드 문자열 순이다. 임상적 중요도 또는 정보이득 최적화 순위가 아니다. 현재 선택은 통증 점수 질문, 체중, BMI, 코드 63512-8, 코드 63586-2, 신장이다. 이 선택은 연동 검증용이며 원본 전체 검사를 사용하는 실험과 다르다. 숫자가 아니거나 여러 source 값이 충돌하는 행동은 자동 범주화하지 않는다.

수치 구간은 학습값 중앙값 이하/초과다. 이는 정상/비정상 임상 판정이 아니다. 모든 학습·평가 조건에 동일한 고정 변환을 적용하고, 원본 evidence JSON도 함께 유지한다. 평가 환자의 결과는 초기 prompt나 확률 추정에 사용하지 않는다. 결과 구간은 실제 해당 행동을 실행한 후에만 관측에 들어간다.

`--max-actions`는 1~12, `--horizon`은 1~3으로 다른 준비 폴더를 만들 수 있다. 기존 준비 결과를 덮어쓰지 않는다. horizon=3/action=12에서 state limit에 걸릴 수 있으므로 기본값은 2/6이다. 행동·표본 선택 후 임상 성능이 좋아졌다고 단정할 수 없으며, 선택 편향과 조건부 독립 가정이 남는다.

## 중요한 완료 범위

**B4의 행동 선택·belief 갱신·재계획은 실행할 수 있지만, 검수된 최종 진단 비교는 아직 완성되지 않았다.** 모델의 `supports_diagnoses`를 임의로 채우지 않았기 때문에, 이 모델이 최종 Diagnose를 선택하면 clinical gate가 허용하는 결과는 **Unresolved**다. 이 상태에서 B3/B4의 최종 진단 정확도를 동등한 임상 조건의 성능 차이로 해석하면 안 된다.

VoI trace에는 통계적 `model_diagnosis`와 belief가 남지만 이는 supported final diagnosis가 아니다. 정식 최종 진단 비교를 하려면 outcome별 진단 지원 annotation/종료 정책을 검토하고 검수된 모델을 별도 revision으로 제공해야 한다. 원본에 없는 의학적 판정 규칙을 생성하거나 기존 diagnostic gate를 약화하지 않았다.

또한 초기 probe로 학습한 B3가 방문 후반 상태에서도 잘 보정된다는 보장은 없다. 유사 학습 관측이 부족하면 명시적으로 abstain하고 ER가 실행한다. 원본 snapshot 시간 가정과 source-dependent 검사 후보 편향도 유지된다.

## 검증

- 준비된 평가 26개 모두 기존 `prepare_encounter` 검증 통과.
- 신규 테스트 3개 통과: test 환자의 숨겨진 값을 변경해도 학습 모델 불변, 공개 후 belief 변경, 실제 B4 Test→재계획→Unresolved 흐름, 행동 집계 중복 방지.
- 전체 회귀: **249 passed**, 실패 0 (24.84초).
- 실제 Ollama 수집/실험은 실행하지 않았다. 준비 결과와 명령을 제공한 상태다.
