# 전문과 선택 원인과 합성 대조 실험

## 1. 실제 선택 근거

`routing_utility.observed_tokens`는 현재 주호소·증상·객관적 결과·known 문진 응답·superseded가 아닌 검색 Memory의 단어 집합을 만든다. `RoutingUtility.score`는 학습 관측과 Jaccard 유사도 J를 계산한다. 양의 유사도가 있는 학습 표본이 min_samples 이상이면:

`estimated_correct(s) = (1 + sum(J_i * correct_i,s)) / (2 + sum(J_i))`

비용·지연은 사용하지 않는다. 이 값은 보정된 임상 확률이 아니라 유사도 가중 성공률 추정치다. AgentRegistry는 가장 큰 값을 선택한다.

최신 실제 Routing 학습 자료는 각 과 66개, 총 330개 모두 correct=false였다. 325개는 Unresolved, 5개는 통증 설명이다. 각 과의 학습 관측은 동일하므로 분모도 같고 분자는 모두 1이다. 따라서 모든 과가 동률이다. 기존 `(-score, department)` 정렬에서 이름순 첫 항목 cardiology가 선택되었다. 심장 질환 근거가 있어서 선택된 것이 아니다.

## 2. 수정

`app/core/agent_registry.py`: 최상위 점수가 절대 오차 1e-12 안에서 둘 이상 같으면 `decision_status=abstained`, `selected_specialty=None`을 반환한다. 후보 메뉴는 유지한다. 기존 실행 정책이 ER 판단을 계속하며 새 LLM router 호출이나 무작위 과 선택을 추가하지 않는다. `tied_departments`, `tie_tolerance`, rationale을 로그에 남긴다. 유일한 최고 점수가 있으면 기존 수식으로 선택한다.

`longitudinal_runner.py`의 policy revision을 갱신해 이전 정책 checkpoint와 혼합 재개하지 않도록 했다. 기존 출력 결과는 다시 계산해 덮어쓰지 않았다.

주의: 동률을 올바르게 보류하는 것이 목적이다. 이 변경만으로 전문과 정답률이나 진단 정확도가 높아진다고 보장하지 않는다. B3/B4가 자주 ER로 돌아간다면 그것도 학습 신호 부족의 결과로 보고해야 한다.

## 3. B0~B2도 낮은 이유

이전 실제 15명 결과는 B0/B1/B2 진단 정답이 1/0/1건이었다. 이 조건은 Adaptive Routing을 쓰지 않으므로 cardiology 동률 문제만으로 설명되지 않는다.

- 초기 관측 및 검색 query가 통증 점수 중심이다.
- 제한된 행동 메뉴는 통증 질문·체중·BMI·기타 공통 수치 등이다. 원본의 모든 진단 관련 검사를 사용한 실험이 아니다.
- target은 source-observed 진단이며, 이 제한된 공개 정보만으로 판별 가능하다고 검수된 정답이 아니다.
- 최종 진단의 exact normalized label 일치로 점수화한다. 후보 이름 목록은 이미 제공되었으므로 단순한 목록 부재로 보기 어렵다.
- 기존 objective-evidence gate는 인용 가능한 객관적 evidence의 존재를 확인하지만 그 evidence가 선택 진단을 의학적으로 입증하는지까지 보장하지 않는다.
- 실제 base model 판단 능력도 별도 검증이 필요하다. 현재 자료만으로 데이터/모델별 원인 비중을 수치로 분해할 수 없다.

## 4. 임의 값 사용: 독립된 합성 대조군

`app/scripts/prepare_hypothetical_pilot.py`를 추가하고 `outputs/hypothetical_control_15_v1/`를 생성했다. 원본 환자의 정답이나 검사값을 수정하지 않는다.

- 가상 환자 15명, 진료과 5개, `Simulation condition 1..5`라는 가상 진단명.
- 가상의 presentation channel에 맞는 전문과는 성공하고 다른 과는 실패한다고 **Routing 기록을 가정**한다. 실제 Ollama 성공률이 아니다.
- 가상 분류 검사의 정답 결과 확률은 **0.85**, 나머지 각 0.0375로 명시한다. `--assumed-reliability`로 다른 가정을 지정할 수 있다.
- 원본 source label을 이용해 실제 검사값을 덮어쓰는 것이 아니라, 독립된 가상 환경의 조건부 분포에서 결과를 생성한다.
- 가상의 검사 결과와 가상 진단의 지원 관계를 명시하므로 B4도 이 합성 세계 안에서는 supported diagnosis로 종료할 수 있다. 실제 데이터 gate나 지원 annotation을 약화하지 않았다.
- seed=42에서 생성한 15개 검사 결과 중 잠재 진단과 일치한 결과는 11개다. **이는 73.3% LLM 정확도라는 뜻이 아니다.** 목표 정확도를 맞추도록 재생성/선별하지 않았다.
- B0~B4가 같은 사례·모델 binding·관측과 행동 환경을 공유한다. 현재 가상 과거 기록은 presentation channel을 반복하므로 Memory 이득을 증명하기 위한 설계가 아니다. H2라도 검사 1개이므로 다단계 우위를 평가하는 설계도 아니다.

가정이 분명한 환경에서 정상 동작하는지 확인하는 control test이며 의료 성능, 임상 검수 데이터, 기존 action_replay 결과와 혼합해 보고하지 않는다. 원하는 정확도를 논문 결과로 만들기 위한 데이터가 아니다.

## 5. 실행

설정 검증은 완료했다. 실제 LLM 호출은 실행하지 않았다. Routing을 가정했기 때문에 330회 수집 단계 없이 바로 실행할 수 있다.

```powershell
python -m app.scripts.run_paper_experiments --plan outputs/hypothetical_control_15_v1/plan.json --conditions B0 B1 B2 B3 B4 --execute --repeats 1 --output-dir outputs/hypothetical_control_15_run1
```

실제 데이터 재실험은 기존 `run_action_replay_all.ps1`을 사용한다. 두 실험은 데이터와 목적이 다르다.

## 6. 검증

- 신규 테스트: all-fail/all-success 동률 abstention, 유일 최고점 선택 유지, 가상 모델 결정론적 생성, 실제 Runner에서 Test 이후 supported diagnosis 흐름.
- 전체 회귀 **254 passed / 실패 0**, 16.07초.
- 합성 plan: 15명 × 5조건 입력 검증 통과, LLM 호출 없음.
