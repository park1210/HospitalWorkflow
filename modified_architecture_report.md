# 수정 결과 — 2026-10-21

## 요약

새 프로젝트/폴더 계층을 만들지 않고 기존 longitudinal runner, parallel scheduler,
memory store, registry, specialist role_call, InformationPolicy를 연결했다.
기존 파일과 과거 실험 입력/결과를 삭제하거나 덮어쓰지 않았다.

**실제 Ollama pilot: 3/3 방문 종료, 전문과 호출 7/7 성공, 실패 0.**
이는 실행 구조 smoke 결과이며 진단 정확도나 임상 검증 결과가 아니다.

## 유지한 구조

- 기존 `python -m app.scripts.run_longitudinal_research` CLI.
- HospitalCaseRuntime/HospitalSchedulerState와 시간·자원·event loop.
- No Memory, Full History, selective lexical, semantic cosine 검색.
- 환자/방문/시간/supersedes 필터 및 기존 registry 모델 이름 binding.
- 기존 `role_call`/OllamaClient 및 기존 ER/SpecialtyAgent 파일.
- source-grounding, 진단 evidence gate, 실패 audit, checkpoint/recovery.
- 기존 outcome 기반 VoI와 IG 계산. 새로운 질환별 분기나 retrieval algorithm은 추가하지 않았다.

## 변경 파일

| 파일 | 변경 |
|---|---|
| `app/core/clinical_observation.py` | `prepare_encounter`, `memory_query`, `encounter_evidence` 추가. 기존 projection 함수 유지 |
| `app/core/longitudinal_runner.py` | encounter 입력 정규화, past_visits 병합/충돌 검사, 매 결정 memory callback, 실행 계약 버전 갱신 |
| `app/core/routing_utility.py` | 비용/지연 차감 제거. 기존 estimator의 context score 반환 |
| `app/core/agent_registry.py` | specialty score argmax, `selected_specialty` audit, fitted coverage 부족 시 기존 keyword score 사용 |
| `app/core/hospital_llm_policy.py` | encounter에서 Memory → 실제 specialty 호출 → 공통 후보/selector, event 기반 Ask/Test/Consult 반환, memory 키 오타 수정 |
| `app/core/hospital_parallel_scheduler.py` | test result ready 시각이 source event available_minute보다 앞서지 않도록 제한 |
| `app/core/information_value.py` | Ask/Test/Consult/Diagnose 공통 candidate interface. 기존 action_values/propose 유지 |
| `app/core/memory_retrieval.py` | 현재 상태 query hash로 저장된 벡터 조회 지원. cosine 수식 유지 |
| `app/core/embedding_builder.py` | encounter 초기 query 및 추가 공개 상태 query 벡터 생성 지원 |
| `app/scripts/build_memory_embeddings.py` | `--query-states` 옵션 |
| `app/scripts/run_longitudinal_research.py` | `--trace`로 memory/routing/model/candidate/action/evidence/final 출력 |
| `app/data/encounter_pilot.json` | 임상 미검수 합성 pilot 3개. 고정 T_LOW/T_HIGH 비교를 사용하지 않음 |
| `tests/test_encounter_pipeline.py` | 소규모 통합·누출 방지·VoI 연결 검사 |
| `existing_architecture_analysis.md` | 수정 전 구조/최소 변경 계획 |

작업 시작부터 존재하던 patient_agent, clinical_followup, patient_facts,
tests/test_memory_research 등 미커밋 변경은 되돌리지 않았다.
hospital_llm_policy/longitudinal_runner는 기존 미커밋 수정 위에 필요한 부분만 수정했다.
Git 전체 diff 규모는 이번 작업만의 규모가 아니다.

## 새 실행 흐름

`index_encounter_id`가 있는 입력에서 다음 경로가 활성화된다.

1. 현재 공개 상태를 구성하고 같은 환자의 과거 기록을 검색한다.
2. `score(specialty | current_state, retrieved_memory)`의 argmax를 계산한다.
3. registry의 선택된 전문과 모델을 기존 `role_call`로 호출한다.
4. 공통 후보 Ask/Test/Consult/Diagnose 중 모델이 제안한다.
5. 명시적 outcome 모델이 주어지면 기존 InformationPolicy로 최종 선택한다.
   적용 가능한 모델이 없으면 전문과 모델의 검증된 제안을 유지하고 selector 종류를 기록한다.
6. 기존 스케줄러가 행동을 실행하고 source event의 evidence만 반환한다.
7. 질문/검사/협진 상태 갱신 후 다시 memory → routing → specialist를 수행한다.
8. Diagnose가 선택되면 기존 종료 처리로 완료한다. 정보 부족 시 unresolved 종료를 허용하는 기존 gate를 유지한다.

전문과 모델의 논리적 선택은 기존 ER 진료 decision point에서도 가능하다.
이는 원격 전문과 모델 자문에 해당하며 새 물리적 전문과 resource 점유를 암묵적으로 추가하지 않는다.
**실제 물리적 이동·전문과 자원 점유는 Consult action이 기존 큐를 통해 처리한다.**
명시적 Consult가 시작되면 요청된 department의 registry binding을 사용한다.

`routing_mode=er_only`는 비교용으로 전문과 자동 실행을 비활성화한다.
그 외 encounter 실행의 담당 모델은 adaptive score argmax를 사용한다.
legacy 입력은 기존 ER/협진 흐름을 유지하지만 adaptive score 수식 자체는 변경되었으므로
기존 논문 결과와 새 실행 결과를 같은 구현으로 간주하면 안 된다.

## Routing 수식

기존 Jaccard sample matching은 재사용한다.

```
w_i = Jaccard(tokens(current_state, memory), training_tokens_i)
score(s) = (1 + sum_i w_i * correct_i) / (2 + sum_i w_i)
selected = argmax_s score(s)
```

비용·지연·accuracy weight는 선택 점수에 반영하지 않는다.
기존 artifact와 호출 코드 호환을 위해 class 이름, `utility` 반환 alias,
weights/cost/latency 입력 메타데이터는 남아 있으며 `utility == score`이다.
충분한 fitted coverage가 없으면 기존 keyword overlap score로 전체 후보를 비교한다.
동점은 canonical department 이름 순서로 처리한다. 점수 0 동점도 하나를 선택하므로
임상적으로 잘 보정된 routing confidence를 뜻하지 않는다.

## Encounter 입력 계약

```json
{
  "case_id": "example-v1",
  "longitudinal": {"patient_id": "example"},
  "index_encounter_id": "v1",
  "index_encounter_start": "2026-03-01T00:00:00Z",
  "primary_specialty": "neurology",
  "past_visits": [
    {
      "visit_id": "v0",
      "started_at": "2026-01-01T00:00:00Z",
      "records": ["실제 입력에서는 기존 PatientMemoryStore 스키마의 객체"]
    }
  ],
  "current_initial_state": {
    "doctor_visible_info": {"chief_complaint": "...", "initial_vitals": {"spo2": 98}},
    "patient_visible_info": {"history": "..."}
  },
  "current_encounter_events": [
    {
      "event_id": "result-1",
      "action": "Test",
      "target": "검사 이름",
      "available_minute": 8,
      "evidence": "원본에 존재하는 결과"
    }
  ]
}
```

위 records 문자열은 문서 설명용이다. 실행 가능한 전체 객체는 `app/data/encounter_pilot.json` 참조.
`primary_specialty`는 라벨/설명용이며 agent 관찰이나 라우터 토큰으로 보내지 않는다.
legacy longitudinal.visit_id/started_at도 있으면 index 정보와 일치해야 한다.
past_visits에는 이전 방문만 허용하고, 다른 환자·미래 이용 가능 기록은 조용히 넣지 않고 오류 처리한다.
초기 공개 정보는 caller가 실제 encounter 시작 시점의 정보만 넣어야 한다.
텍스트에 실제 미래 내용을 잘못 넣었는지는 시스템이 임상적으로 판별할 수 없다.

### Source event 환경

- Ask: 원본의 정확한 question target을 선택하고 evidence 문자열을 그대로 반환한다.
  별도의 환자 LLM 호출을 하지 않는다. 기존 PatientAgent는 legacy 경로에 유지된다.
- Test: 원본 target만 후보로 제공한다. 검사 수행 후 `available_minute` 이전에는 결과를 공개하지 않는다.
  스케줄러의 가상 검사 시간과 source 공개 시각 중 더 늦은 시각을 따른다.
- Consult: 원본에 존재하며 공개 가능한 전문과만 추가 협진 후보로 제공한다.
  전문과 모델은 호출하지만 의학적 evidence는 원본 consult note만 사용한다.
- Diagnose: 새 source event를 생성하지 않고 기존 종료 처리를 수행한다.
- 원본에 없는 target/result를 생성하지 않는다.
- legacy hidden_test_results, temporal progression, test_access는 strict encounter adapter에서 사용하지 않는다.
  새 event 계약은 Ask/Test/Consult evidence만 다루며 상태 생리 악화 재생은 이번에 추가하지 않았다.
- Test 이름은 구조적 action catalog로 보이지만 결과 본문과 미래 event 전체는 초기 agent input에 전달되지 않는다.

## Memory와 semantic 지원 범위

현재 공개 상태의 chief_complaint, current_symptoms, vital_signs, history,
objective_findings, consults, working_assessment를 직렬화하여 query를 만든다.
working_assessment는 모델의 이전 의견이며 사실 확인된 진단은 아니다.
기존 lexical overlap/cosine/top-k/시간 필터를 그대로 사용한다.
top_k와 none/full_history/selective/semantic은 기존 CLI로 조절한다.

기존 v4 semantic artifact는 주호소-only query에 묶여 있어 새 query에 재사용할 수 없다.
`build_memory_embeddings --query-states`는 공개 observation 목록을 받아 query hash별 벡터를 만든다.
실행 중 나온 query에 일치하는 벡터가 없으면 명시적으로 실패한다.
자동 임베딩 호출이나 lexical fallback은 추가하지 않았다.
이번 실제 smoke는 **selective, top_k=1**이며 새 semantic 성능 실험은 하지 않았다.

## 실행 명령

새 출력 파일명을 사용한다.

```powershell
python -m app.scripts.run_longitudinal_research `
  --cases app/data/encounter_pilot.json `
  --output outputs/encounter_pilot_next.json `
  --memory-mode selective --top-k 1 --memory-source fixed `
  --agent-registry app/data/challenge_v4/registry.json `
  --routing-mode adaptive --minute-limit 60 --max-retries 0 --trace
```

비교: `--memory-mode none` 또는 `--memory-mode full_history`.
pilot은 기존 registry의 qwen-neurology:latest/qwen-pulmonology:latest를 사용한다.
이번 작업에서 adapter를 재학습/교체하지 않았으며 해당 Ollama 모델 내부 LoRA 구성은 별도 검증하지 않았다.

## 실제 Ollama smoke 결과

출력: `outputs/encounter_pilot_live_20261021.json`
checkpoint: `outputs/encounter_pilot_live_20261021.checkpoint.json`

실행 설정: max_retries=0, minute_limit=60, LLM timeout=60초, max_output_tokens=512.

| 사례 | Memory | 실제 호출 | 행동 | 결과 |
|---|---|---|---|---|
| p001 | 과거 기록 1개 | qwen-neurology 2회 | Test → Diagnose | 종료; `unresolved presenting problem` |
| p002 | 과거 기록 1개 | qwen-pulmonology 2회 | Test → Diagnose | 종료; `Exertional breathing difficulty and respiratory symptoms` |
| p003 | 없음 | qwen-neurology 2회 + qwen-pulmonology 1회 | Ask → Consult → Diagnose | unresolved 종료 |

- p001 검사 결과는 가상 8분에 공개되어 source available_minute=8을 준수했다.
- p002 검사 결과는 가상 5분에 공개되었다.
- p003 질문 응답 및 협진 의견은 원본 event 본문과 일치한다.
- 모든 실제 호출 backend는 `OllamaClient`, status는 success였다.
- gold diagnosis를 지정한 정확도 평가가 아니므로 정확도 수치를 산출하지 않는다.
- 일부 모델 rationale은 객관적 근거가 없는데도 “Objective findings”라고 서술하거나 문장이 끊겼다.
  모델의 rationale을 검증된 임상 evidence로 승격하지 않는다.
- 기존 test summary의 `synthetic:false`는 fixture의 임상 출처를 검증한 표시가 아니다.
  이번 pilot 전체가 직접 작성된 미검수 합성 데이터이다.
- live 실행 이후 추가한 query audit/trace 및 deadline의 source 시각 검사 보강은 아래 offline 검사로 확인했다.
  동일 3개 사례를 반복해서 추가 LLM 호출하지 않았다.

## Offline 검사

실행:

```
python -m unittest discover -s tests -p test_encounter_pipeline.py -v
python -m unittest discover -s tests -p test_longitudinal_memory.py -v
python -m unittest discover -s tests -p test_voi_minimal.py -v
python -m unittest discover -s tests -p test_agent_registry.py -v
```

결과: encounter 8, memory 10, VoI 4, registry 6 = **28개 통과**.
encounter의 3-case 연결 검사는 `ScriptedSpecialist`라는 명시적 test double을 사용한다.
이는 위 실제 Ollama 3-case smoke와 구별된다.
추가로 specialty 호출 후 기존 VoI가 source-backed 후보를 선택하는 경로,
비용/지연 변경에 대한 routing 불변성, expanded query hash 검증을 검사했다.

## 임시/미완료인 부분과 다음 Bayesian 단계

1. **실제 pilot의 action selector는 specialist heuristic**이다.
   새로운 임상 outcome likelihood를 임의로 만들지 않았으므로 pilot에 VoI model을 전달하지 않았다.
2. 기존 Bayesian/finite-horizon selector는 유지되고 encounter 뒤에 연결되어 offline 검사를 통과했다.
   이를 실데이터에 적용하려면 action별 P(outcome | diagnosis, state),
   diagnosis prior, terminal utility, 비용, stopping calibration이 필요하다.
3. 현재 specialist는 candidate 중 하나를 제안한다. 별도의 모든 후보별 calibrated benefit 추정은 없다.
   정식 VoI 교체 지점은 `InformationPolicy.propose`/`action_values`와 outcome artifact다.
4. 기존 categorical exact-text observation 모델은 임상 자유문장 전체를 일반화하지 못한다.
5. source event 부재는 행동 후보 부재로 이어진다. 실제 데이터에서 검사가 “불가능”한 것과
   “기록되지 않은 것”의 차이를 구분하는 annotation이 다음 단계에 필요하다.
6. specialist logical call의 실제 latency와 scheduler의 물리적 consult time은 별개다.
7. semantic 동적 query의 미리 저장되지 않은 상태에 대한 온라인 벡터 공급은 아직 없다.
8. unresolved 종료와 clinically correct diagnosis는 다르다. 임상 검수 라벨과 별도 정확도 평가가 필요하다.

이전 B0–B4 결과는 보존되어 있지만 변경된 router와 encounter flow의 성능 결과로 재사용하면 안 된다.
