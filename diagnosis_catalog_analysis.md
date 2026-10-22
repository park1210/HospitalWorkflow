# 진단/진료과 목록 및 최신 15명 결과 확인

근거: `outputs/action_replay_pipeline_20261022_044617_fd9e07/results/` 및 같은 실행의 `routing_train.json`. 기존 결과는 수정하지 않았다. 새로운 실제 LLM 실험은 실행하지 않았다.

## 기존 성능

| 조건 | 완료 | 진단 정답 | 최종 진료과 정답 | 미확정 진단 |
|---|---:|---:|---:|---:|
| B0 | 15/15 | 1/15 (6.7%) | 2/15 (13.3%) | 0 |
| B1 | 15/15 | 0/15 (0%) | 1/15 (6.7%) | 0 |
| B2 | 15/15 | 1/15 (6.7%) | 4/15 (26.7%) | 0 |
| B3 | 15/15 | 1/15 (6.7%) | 1/15 (6.7%) | 3 |
| B4 | 15/15 | 0/15 (0%) | 3/15 (20%) | 15 |

진료과 수치는 기존 집계의 `final_department_accuracy`이며 primary routing accuracy와 다르다. 완료는 진단 정답을 의미하지 않는다. source-observed 정답과 임상 검수 gold도 동일하지 않다.

## 목록은 있었는가?

- paper runner는 모든 조건에 `voi_model.diagnoses`의 15개 진단명을 `diagnosis_catalog`로 전달했다. 각 report에서도 확인된다. `HospitalLLMPolicy._decision`은 payload와 Diagnose target enum에 이를 사용한다.
- 진료과는 공유 `SUPPORTED_DEPARTMENTS` enum 및 registry에 이미 있다. 신규 registry를 만들 필요는 없다.
- 부족했던 부분은 공통 진단↔진료과 연결표의 prompt 전달, 단독 longitudinal CLI에서 진단 목록을 지정하는 옵션, Routing probe의 공통 진단 후보 목록이다.

## 확인된 실패 요인

1. Routing 학습 330행 모두 correct=false. 325행은 Unresolved, 나머지 5행은 통증 점수를 설명하는 문장이다. 전문과별로 각각 66행 모두 오답이었다. 다섯 과가 동일 관측과 동일 실패 결과를 가지므로 모든 점수가 같다. 첫 환자는 다섯 과 모두 0.044948848476735255였으며, 이름순 동률 처리로 cardiology가 선택됐다. B3/B4 각각 초기 15건 모두 cardiology다. 이는 올바른 전문과를 학습한 결과가 아니다.
2. B4의 supports_diagnoses는 의도적으로 비어 있다. 이번 15건도 모두 diagnosis_unresolved다. 임상 근거 annotation 없이 알고리즘 출력만 supported로 바꾸지 않는다.
3. 사용한 행동은 통증 질문, 체중, BMI, 코드 63512-8, 코드 63586-2, 신장이다. 초기 정보와 행동 공간이 제한되어 있다. 목록을 추가하는 것만으로 정보 부족이 해소되지는 않는다. 검사 추가는 학습/평가 동일 메뉴와 outcome model을 함께 재설계해야 한다.
4. B0/B1/B2/B3의 출력 진단과 study taxonomy상의 진료과 불일치가 각각 6/9/6/8건이다. 연결표를 prompt로 제공하는 것은 이 오류를 줄이기 위한 조치지만, 개선량은 재실행 전 확인 불가다. 현재 결과를 사후 덮어쓰거나 정답 진료과에 강제 맞추지 않았다.

## 변경 및 목록 파일

- `app/data/action_replay_diagnosis_catalog.json`: 공통 진단 15개.
- `app/data/action_replay_department_catalog.json`: 공통 진료과 5개.
- `app/data/action_replay_diagnosis_departments.json`: 공통 연결표.

세 파일은 최신 실험의 고정된 VoI artifact에서 추출한 **연구용 taxonomy**다. 보편적인 임상 진료과 분류로 주장하지 않는다. 환자별 정답 키나 개인별 정답 목록은 포함하지 않는다.

- `longitudinal_runner.py`: 선택적 diagnosis_departments 인자 검증·보고·재개 계약 반영.
- `hospital_llm_policy.py`: 공통 연결표와 진료과 목록을 전달. 목록은 환자 근거가 아님을 명시.
- `run_paper_experiments.py`: 모든 조건에 동일한 연결표 전달.
- `run_longitudinal_research.py`: `--diagnosis-catalog`, `--diagnosis-departments` 지원.
- `collect_routing_outcomes.py`: `--diagnosis-catalog` 지원, Unresolved 유지. 모든 probe에 같은 후보 제공.
- `prepare_action_replay_study.py`: 새 준비 결과의 probe에도 공통 후보 포함.
- `run_action_replay_all.ps1`: 수집 단계에 공통 후보 자동 연결, B0~B4 동일 15명 실행. PowerShell preview의 환자 수가 1로 표시되던 배열 Count 문제 수정. 기본값은 최근 실행과 환자 ID가 일치하는 `action_replay_study_15_v2`다.

단독 실행에서 목록을 쓰려면 기존 명령에 다음을 추가한다:

```powershell
--diagnosis-catalog app/data/action_replay_diagnosis_catalog.json --diagnosis-departments app/data/action_replay_diagnosis_departments.json
```

통합 스크립트는 자동으로 연결한다. 기존 330행 학습 자료는 전부 오답이므로 이 자료를 재사용해서 좋은 Adaptive 성능을 기대하면 안 된다. 공통 목록을 제공해도 관측 근거 부족으로 Unresolved가 유지될 수 있다. 단지 목표 정확도를 맞추려고 강제 진단을 요구하지 않는다.

## 검증과 다음 판단

실제 모델 호출 없이 관련 테스트 10개 통과. 공통 목록/연결표 전달, report 보존, 비정규 진료과·불완전 연결표 거부, 기존 Runner/VoI 동작을 확인했다.

70%는 현재 확인된 결과가 아니라 사용자 목표다. 15명에서는 11명 정답이 73.3%이며, 이 작은 표본만으로 일반화 성능을 주장할 수 없다. 우선 학습 probe에 진단 구분 정보를 제공할 수 있는지, 검사의 진단 관련성과 source label의 실제 평가 타당성, B4 지원 annotation을 검토해야 한다. 같은 평가 15명을 반복해서 맞추는 전용 규칙을 추가하지 않는다.
