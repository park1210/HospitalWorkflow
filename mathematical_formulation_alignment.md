# 수학적 formulation 정렬

2026-10-21. 기존 Memory → Routing → Specialty Agent → Action Selection과 scheduler를 유지했다.
새 Synthea 연결, 실제 LLM 호출, 임상 outcome 생성은 수행하지 않았다.
이번 결과는 categorical toy 및 offline regression 검사다.
이 문서는 이전 `modified_architecture_report.md`의 threshold/finite-horizon 설명을 대체한다.

## 변경 전과 변경 후

| 항목 | 변경 전 | 현재 |
|---|---|---|
| Memory | 공개 state query + 기존 lexical/cosine | 유지 |
| Routing | 비용/지연 없는 estimator이나 baseline 역할 불명확 | RuleSimilarityRouter baseline으로 표시, 공통 primary-router interface |
| Belief | VoI 내부 dict, model 없음 상태 불명확 | DiagnosisBelief(probabilities/status/reason), 없음은 null |
| Candidate | type/action/target | action_id/type/action/target/cost/outcome_model |
| Diagnose | probability threshold 또는 budget으로 먼저 종료 | Q_Diagnose를 다른 Q와 직접 비교, 동점이면 Diagnose |
| Information Q | horizon에 따른 다단계 continuation | 요청 수식의 one-step terminal expectation |
| Selector | VoI/heuristic 중심 | Random / Specialist heuristic / IG / Bayesian VoI 구분 |
| Missing model | fallback 해석이 모호 | unavailable + reason + executed_selector 명시 |

## 1. Memory

\[
q_t=f(x_t),\quad s_i=Sim(E(m_i),E(q_t)),\quad
M_t^*=\operatorname{TopK}_{i\in\mathcal{F}_t,\ s_i>0}s_i.
\]

- `clinical_observation.memory_query`: chief_complaint, current_symptoms,
  vital_signs, history, objective_findings, consults, working_assessment의 공개 값만 직렬화한다.
- gold label, primary_specialty, unreleased event 본문은 사용하지 않는다.
- `PatientMemoryStore.retrieve`: 동일 환자, 다른 이전 방문, 당시 이용 가능한 기록,
  non-superseded 조건으로 후보를 만든다.
- `selective`: casefold/단어 집합의 교집합 크기. 학습 embedding을 사용한다고 설명하면 안 된다.
- `semantic`: 사전 저장 벡터의 L2-normalized cosine. E는 저장 벡터 생성 모델이다.
- **실제 구현에는 s>0 조건이 있다.** 무조건 정확히 K개를 돌려주는 수식이 아니라 최대 K개다.
- 점수 동점은 available_at 최신순, memory_id 순. 문자 예산이 있으면 선택 후 적용한다.
- `none`: 빈 목록. `full_history`: 환자/방문/시간 조건을 만족하는 전체 기록
  (superseded도 상태를 표시하여 포함). 이 두 조건에는 TopK 수식을 적용하지 않는다.
- 기존 retrieval algorithm은 변경하지 않았다.
- legacy patient case는 chief complaint query를 유지하며 encounter 입력에서 f(x_t)를 사용한다.
- semantic의 동적 query hash에 맞는 벡터가 없으면 오류다. 임의 벡터나 숨은 lexical fallback은 없다.

## 2. Routing

\[
score_s=s_\theta(s,x_t,M_t^*),\qquad
s^*=\arg\max_s score_s.
\]

`AgentRegistry.select_specialty(current_state, retrieved_memory, departments, router=...)`
가 공통 interface다.

| router 인자 | 구현 상태 |
|---|---|
| rule_similarity | 기존 Jaccard estimator/keyword baseline 사용, router 명칭 RuleSimilarityRouter |
| llm | unavailable / router_not_implemented |
| memory_aware_llm | unavailable / router_not_implemented |

반환값은 router/status/specialty_scores/selected_specialty 등을 포함한다.
LLM router를 요청했는데 RuleSimilarityRouter로 몰래 대체하지 않는다.
기존 `route(mode="llm")`는 legacy consultation menu 모드이며 새 LLM Router의 구현이 아니다.

baseline의 fitted score:
\[
w_i=Jaccard(tokens(x_t,M_t^*),tokens_i),\quad
score_s=\frac{1+\sum_i w_i\,correct_i}{2+\sum_i w_i}.
\]

이 값은 **보정된 진단 확률이 아닌 similarity-weighted baseline score**다.
coverage 부족 시 기존 keyword overlap을 사용하고 명칭과 rationale에 표시한다.
비용/latency/accuracy weight는 점수 선택에 반영하지 않는다.
기존 artifact/연구 도구 호환을 위해 RoutingUtility 이름과 utility/estimated_correct 필드가 남지만,
utility는 score의 alias이고 estimated_correct도 calibrated probability를 보장하지 않는다.
비용/latency는 감사용 메타데이터다.

## 3. Belief 및 Bayesian update

`diagnostic_belief.DiagnosisBelief`:

```json
{"probabilities": null, "status": "unavailable", "reason": "missing_outcome_model"}
```

명시적 model이 있는 경우에만 유한 확률 dict를 저장한다. 각 값은 [0,1], 합은
절대오차 1e-9 이내에서 1이어야 한다. model이 없다고 균등 prior를 만들지 않는다.
`runtime.voi_state.diagnosis_belief`에 상태를 기록한다.

\[
P(o|b,a)=\sum_d b(d)P(o|d,a),\qquad
b'(d)=\frac{b(d)P(o|d,a)}{\sum_j b(j)P(o|j,a)}.
\]

`posterior`가 정규화와 predictive mass를 계산한다.
확률 0인 관찰을 실제 관찰하면 오류이며, 기대값 계산에서 확률 0 branch는 건너뛴다.
`InformationOutcomes.observe`는 공개된 관찰만 exact categorical matching한다.
현재 관찰이 모델 밖이면 unavailable/unsupported_observation으로 기록하고 stale belief를 제거한다.

## 4. 공통 Action

`information_value.candidate_actions`:

```json
{
  "action_id": "Test 1",
  "type": "Test",
  "action": "request_test",
  "target": "Test 1",
  "cost": {"money": 0.1, "minutes": 0, "tokens": 0},
  "outcome_model": "Test 1"
}
```

type은 Ask/Test/Consult/Diagnose, action은 기존 scheduler/validator 이름을 유지한다.
outcome_model은 같은 artifact의 action ID 참조다.
model이 없으면 information action의 cost/outcome_model은 null이다. 0이라고 가정하지 않는다.
Diagnose는 추가 정보 취득 비용 0이며 효용은 terminal utility로 평가한다.
Ask/Test/Consult 실행 결과는 기존 source event에서만 반환한다.

## 5. Diagnose value / stopping

\[
Q(b,\mathrm{Diagnose})=\max_{\hat d}\sum_d b(d)U(\hat d,d)
=V(b).
\]

- `terminal_choice`: 최적 진단과 기대 terminal utility.
- `validation_utility`: correct=1, incorrect=0 기본값을 변경 가능한 함수 인자로 지원.
- utility matrix가 없으면 InformationOutcomes가 이 test utility를 만들고
  provenance.utility_scope=algorithm_validation_only를 명시한다.
- 이는 임상 효용이 아니다. 비용/진단별 위해가 검증된 utility matrix로 교체해야 한다.
- `select_action(selector="bayesian_voi")`는 Diagnose도 Q값 비교에 포함한다.
- Q값 동점이면 추가 호출을 피하도록 Diagnose가 우선한다.
- `stop_probability`는 선택에 사용하지 않는다. legacy schema 호환용 입력만 남아 있다.
- `horizon`도 legacy 입력을 읽을 뿐 현재 Q 계산은 항상 one-step이다.

### 알고리즘 선택과 임상 support의 구분

Q가 Diagnose를 선택하면 prior 상태에서도 종료할 수 있다.
하지만 현재 evidence gate는 그대로 유지한다. 모델상 선택 진단은
selector_status.selected_action.target 및 history.model_diagnosis에 남기고,
공개 객관적 근거가 없으면 실제 simulation 완료는 unresolved로 표시한다.
따라서 model-based terminal choice를 임상 확진으로 부르면 안 된다.
별도 confidence threshold 때문에 계속 검사를 강제하지 않는다.

## 6. Information action Q / VoI

\[
C(a)=\sum_k cost\_weight_k\,cost_k(a)
\]
\[
Q(b,a)=-C(a)+\sum_o P(o|b,a)V(b^{a,o})
\]
\[
VoI(a)=\sum_oP(o|b,a)V(b^{a,o})-V(b)-C(a)
=Q(b,a)-Q(b,\mathrm{Diagnose})
\]
\[
a^*=\arg\max_{a\in\mathcal{A}_t\cup\{\mathrm{Diagnose}\}}Q(b,a).
\]

`action_values`: expected_continuation_utility, q_value, cost_penalty, voi를 분리하여 반환.
각 action의 diagnosis별 outcome likelihood 합=1, 유한 비음수 비용을 검증한다.
T_LOW/T_HIGH 이름이나 임의 confidence threshold에 의존하는 분기는 없다.
기존 challenge 데이터 파일은 재현 자료이므로 삭제하지 않았다.

## 7. Information Gain

\[
H(b)=-\sum_d b(d)\ln b(d),\qquad
IG(a)=H(b)-\sum_oP(o|b,a)H(b^{a,o}).
\]

entropy는 nats 단위다. 비용은 IG에 포함하지 않는다.
`select_action(selector="information_gain")`는 IG로 순위를 매기고 Diagnose의 IG=0이다.
IG가 모두 0이면 Diagnose가 동점 우선이다.
IG selector에서도 model은 필요하지만 IG를 VoI라고 부르지 않는다.
동일 action의 IG/VoI가 함께 기록되는 것은 진단용 지표이며 선택 기준은 selector 필드로 구분한다.

## 8. Selector 상태와 grounding

공통 함수:

```
select_action(candidates, selector=..., belief=..., artifact=...,
              specialist_proposal=..., seed=...)
```

지원 이름: random, specialist_heuristic, information_gain, bayesian_voi.
random은 seed를 사용하고, heuristic은 전문과 제안을 반환한다.
실행 loop의 Random은 실제 target을 지정할 수 있는 후보에서 선택한다.
자유형 Ask/Diagnose의 target이 아직 없는 경우 해당 모델 제안이 있어야 실행 후보에 포함된다.

model 부재:

```json
{
  "selector": "bayesian_voi",
  "status": "unavailable",
  "reason": "missing_outcome_model",
  "executed_selector": "specialist_heuristic"
}
```

이때 Q/VoI를 임의로 채우지 않는다. 종료 가능한 기존 specialist 흐름은 계속 사용하되
**요청한 selector가 사용 불가였고 실제로 heuristic을 사용했음**을 audit와 voi_state에 기록한다.
encounter의 일부 source action만 model이 있으면 missing_action_outcome_model로 반환한다.
관찰과 model이 불일치하면 unsupported_observation이다.

legacy patient-only 입력은 기존 artifact가 정의한 action catalog를 비교 대상으로 유지한다.
history.candidate_scope=legacy_model_catalog로 표시하며 전체 임상 행동이 모델링됐다고 주장하지 않는다.
새 encounter는 candidate_scope=source_events이며 모든 현재 후보의 model coverage를 확인한다.
공통 select_action 함수도 전달받은 후보 중 model이 없는 정보 행동을 무시하지 않고 unavailable을 반환한다.

CLI:

```
python -m app.scripts.run_longitudinal_research ... --action-selector bayesian_voi --voi-model MODEL.json
```

--voi-model 없이 위 selector를 요청하면 사용 불가 상태가 기록된다.
기본값은 model이 있으면 bayesian_voi, 없으면 specialist_heuristic이다.
이번 작업에서는 실제 CLI model 실험을 실행하지 않았다.

## 9. Routing과 Consult

Routing은 현재 판단을 수행할 primary specialty 모델을 고른다.
Consult는 현재 담당 전문과 외의 추가 opinion을 얻는 정보 행동이다.
기존 available_consult_departments의 current 제외 및 반복 제한을 유지한다.
source에 없는 consult evidence를 전문과 모델의 자유 생성 문장으로 대체하지 않는다.

## 10. 함수 ↔ 수식 mapping

| 수식/역할 | 파일 / 함수 |
|---|---|
| q=f(x) | clinical_observation.py / memory_query |
| 후보 시간/환자 필터 및 TopK | longitudinal_memory.py / PatientMemoryStore.retrieve |
| cosine | memory_retrieval.py / MemoryEmbeddings.scores |
| score(s,x,M), argmax | agent_registry.py / select_specialty, route; routing_utility.py / score |
| b, 정규화 검증 | diagnostic_belief.py / DiagnosisBelief, distribution |
| Bayes update / P(o|b,a) | diagnostic_belief.py / posterior |
| H(b) | diagnostic_belief.py / entropy |
| Q(Diagnose) | diagnostic_belief.py / terminal_choice |
| Q(a), VoI(a), IG(a) | information_value.py / action_values |
| 모든 전달 후보 비교 | information_value.py / select_action |
| source/model 후보 연결, selector status | information_value.py / InformationPolicy.propose |
| 전문과 호출 후 선택, unavailable 시 명시적 heuristic 실행 | hospital_llm_policy.py / _decision |
| 실행 옵션/재개 계약 | longitudinal_runner.py / run_longitudinal |

## 11. Toy validation

실제 의료 데이터가 아닌 `tests/test_mathematical_alignment.py: toy()`:

| 변수 | 값 |
|---|---|
| 진단 | A/B |
| prior | 0.5 / 0.5 |
| Test 1 positive likelihood | P(+|A)=0.9, P(+|B)=0.1 |
| Test 1 negative likelihood | P(-|A)=0.1, P(-|B)=0.9 |
| Test 2 positive/negative | 각 진단에서 각각 0.5 |
| test 비용 | 각각 0.1 |
| correct/incorrect utility | 1 / 0 |

검증값:

| 항목 | Test 1 | Test 2 |
|---|---:|---:|
| positive predictive probability | 0.5 | 0.5 |
| positive posterior A | 0.9 | 0.5 |
| expected terminal value | 0.9 | 0.5 |
| Q | 0.8 | 0.4 |
| VoI | 0.3 | -0.1 |
| IG (nats) | 0.3680642071684971 | 0 |

Q(Diagnose)=0.5, H(prior)=ln(2).
Test 1 비용을 0.2 올리면 VoI가 정확히 0.2 내려가고 IG는 변하지 않는다.
prior=[0.99,0.01]에서는 Diagnose 선택.
비용이 2인 Test 1은 Bayesian VoI에서 선택되지 않지만 IG에서는 선택된다.
model 없음/부분 부재는 unavailable이고 숫자를 생성하지 않는다.

실행한 offline 검사:

| 테스트 파일 | 통과 |
|---|---:|
| test_mathematical_alignment.py | 12 |
| test_encounter_pipeline.py | 8 |
| test_voi_minimal.py | 4 |
| test_longitudinal_memory.py | 10 |
| test_agent_registry.py | 6 |
| test_memory_research.py | 15 |
| 합계 | 55 |

기존 test 파일의 assertions를 약화하거나 삭제하지 않았다.
cost/latency 변경으로 routing score가 바뀌지 않는 검사는 기존 encounter test에 포함되어 있다.

## 12. 실제 데이터에서의 사용 가능 범위

사용 가능: 공개 상태 query, 기존 검색, baseline routing, 전문과 호출,
source-grounded Ask/Test/Consult/Diagnose, heuristic 및 명시적 selector status.

아직 실데이터로 주장할 수 없는 것:

- counterfactual likelihood가 없는 실제 action의 Bayesian Q/VoI/IG
- 임상적으로 보정된 diagnosis prior/posterior 또는 routing probability
- 임상 검증된 terminal utility / cost 변환
- 새 LLM Router와 Memory-aware LLM Router
- Synthea 데이터 통합 및 임상 outcome 평가 (이번 작업 범위에서 제외)

이전 실제 pilot 결과를 이번 수식 변경 후의 실제 모델 성능이라고 재사용하면 안 된다.
