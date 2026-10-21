# Primary Router 실행 경로 연결

## 실제 실패 후 보완한 내용

- Router instruction에 **모든 후보 key, JSON 숫자, 0~1 범위, 합계 1 불필요**를 명시했다. 잘못된 score를 임의로 나누거나 0으로 바꾸지 않는다.
- Diagnose schema에 전문과 catalog/alias를 target으로 제출하지 못하는 제약과 설명을 추가했다. 기존 supported diagnosis의 objective evidence 검증은 유지했다.
- `role_call.py`에 알려진 `routing_score_contract`, `diagnosis_is_department` 오류에 한해서 **같은 모델에 최대 1회 교정 요청**을 추가했다. 같은 입력 관측과 구체적인 계약 오류를 전달하며 새 임상 사실 생성을 금지한다. 교정도 동일 validator를 통과해야 하고, 다시 실패하면 중단한다. JSON 파싱 실패/timeout/연결 실패 등의 자동 재시도는 추가하지 않았다.
- 첫 실패와 교정 요청을 모두 audit에 남긴다. `validation_detail`에 field/type/value_repr, `invalid_response`에 최대 4,096자의 실패 원문, SHA-256 및 truncation 여부를 남긴다. 실패한 요청 비용도 유지하므로 case가 completed여도 repaired error audit가 있을 수 있다.
- Router 캐시는 모델·current state·실제 전달 memory·후보·schema·prompt가 같은 경우에만 사용한다. 이전에 검증된 성공 결과만 저장한다. 메모리를 사용하지 않는 LLMRouter에서는 memory만 바뀌어도 캐시를 사용할 수 있다. cache_hit은 routing_history에 남기며 실제 호출 횟수에는 더하지 않는다.
- 기본 호출 한도를 **총 16회 / Router 8회 / 임상 8회**로 분리했다. 교정 요청도 한도에 포함한다. `--max-model-calls`, `--max-router-calls`, `--max-clinical-calls`로 지정할 수 있으며 `model_call_counts`, `model_call_limits`를 결과에 기록한다. 경계를 넘는 요청은 전송하지 않는다.
- 첫 결과는 `initial_routing`, 마지막 결과는 기존 `routing`, 성공한 경로 이력은 `routing_history`에 보존한다. `initial_routing_evaluation` 및 summary의 `initial_*_accuracy`는 초기 라우팅만 별도 평가한다. 실패한 후속 Router 요청은 router_audit에서 확인한다.
- repair/cache 계약이 달라졌으므로 runner의 policy revision을 올려 이전 checkpoint와 혼합 재개하지 않도록 했다.

후속 검증: **총 41개 검사 통과**(기존 36개 + 실패 재현 5개). 숫자 범위/문자열/bool/NaN 오류, 반복 오류 중단, 캐시 무효화, 역할별 요청 한도, 실제 loop에서 전문과명 진단 교정, timeout 무재시도를 모의 응답으로 검사했다. 실제 Qwen/Ollama에서 실패율이 개선됐는지는 `_02` 실행으로 확인해야 한다.

```powershell
python -m unittest discover -s tests -p test_routing_failure_fixes.py
```

## 결과

기존 simulation loop에 RuleSimilarityRouter, LLMRouter, MemoryAwareLLMRouter를 연결했다. 실제 실행 결과는 `runtime.voi_state.primary_routing`에서 읽어 pilot JSON에 저장한다. LLM router 실패 또는 offline 중단을 Rule 결과로 바꾸지 않는다.

실제 Ollama 실험은 이번 변경 검증에서 실행하지 않았다. 모의 응답을 사용한 실행 경로 검사 및 임시 JSON 저장 검사만 수행했다. 소스 benchmark SHA-256은 `3674b7afe90e4dfe58b7922d3572761a59c62cb6d3dcb73097a5a615f3e98729`로 불변이다.

## 변경 파일

| 파일 | 변경 |
|---|---|
| `app/core/hospital_llm_policy.py` | `primary_router_mode` 기본값 및 3개 분기. LLM router 모델은 registry의 ER binding에서 선택. 실제 결과/실패를 runtime에 저장. Router audit는 임상 action count에서 제외 |
| `app/core/longitudinal_runner.py` | keyword-only `primary_router` 추가, 값 검증, scheduler 전달, routing_config/실험 및 resume signature 반영 |
| `app/core/specialty_router.py` | 성공/실패 결과를 router audit에 기록. score 의미 명시. 잘못되거나 빠진 score를 0으로 보충하지 않고 검증 실패 처리 |
| `app/llm/role_call.py` | 알려진 계약 오류의 최대 1회 교정, 원문/필드 진단 로그, 시도별 audit 유지 |
| `app/scripts/run_synthea_v2_pilot.py` | `--primary-router`, router payload 구분, 실제 runtime routing 사용, registry binding 검증, router audit 저장. live smoke 실패 시 전체 pilot으로 진행하지 않음 |
| `tests/test_primary_router_integration.py` | Router 입력/출력, 실패, registry 연결, signature, CLI 저장 JSON 검증 8개 추가 |
| `tests/test_synthea_v2_integration.py` | 기존 test args에 현재 필수 memory budget 설정 추가 |
| `tests/test_encounter_pipeline.py` | 이전 working_assessment 기반 검색 테스트를 현재 공개 evidence 기반 query 계약에 맞춤 |
| `docs/archive/synthea_v2_model_integration_report.md` | 추천 명단 재실행 결과와 현재 구현 보고서 구분 (과거 문서로 이동) |

변경하지 않은 항목: `agent_registry.py`의 Rule 알고리즘, Patient 동작, Memory 검색/예산 알고리즘, VoI 계산, `app/llm/prompt_loader.py`, specialty별 prompt 파일, `memory_query()`의 working_assessment/consults 제외 동작, shared registry 내용.

## 실행 경로와 비교 조건

| CLI 값 | 실제 router 이름 | Router 입력 | 모델 |
|---|---|---|---|
| `rule_similarity` | `RuleSimilarityRouter` | 기존 current state 및 memory | Router LLM 호출 없음 |
| `llm` | `LLMRouter` | current state만 | registry ER model |
| `memory_aware_llm` | `MemoryAwareLLMRouter` | current state + retrieved_memory | registry ER model |

LLMRouter는 selective 조건에서도 longitudinal_memory를 Router payload에 포함하지 않는다. 단, 뒤에 호출되는 specialty agent는 기존 Memory 조건을 그대로 따른다. MemoryAwareLLMRouter의 no_memory 조건은 빈 retrieved_memory 목록을 전달한다. 모든 후보 전문과는 registry specialty binding 목록에서 온다. gold label은 실행 후 평가에서만 읽는다.

제공된 `app/data/synthea_v2/registry_shared_qwen.json`은 ER 및 17개 specialty binding에 모두 `qwen2.5:1.5b-instruct`를 사용한다. Router도 ER binding의 동일 모델을 사용하므로 요청 명령에서는 shared model 비교가 성립한다. 이 registry는 전문과별 독립 LoRA가 아니라 shared base model 역할 binding이다. 다른 registry를 지정할 경우에는 각 binding의 모델을 사용하며 같은 모델이라고 강제하거나 주장하지 않는다.

- R0: rule_similarity 결과의 no_memory
- R1: rule_similarity 결과의 selective
- R2: llm 결과의 no_memory
- R3: memory_aware_llm 결과의 selective

기존 실행 묶음을 유지한다. Routing pilot은 no_memory/selective, Memory pilot은 no_memory/full_history_budgeted/selective다. 보고서 추천 순서에서 smoke를 고른다.

## 결과와 실패 기록

- `validation.json.primary_router`: 요청된 primary router 설정.
- 각 case의 `primary_router`, `routing.router`, `routing.status`, `routing_result_source`, `router_model`, `router_audit`, `binding`을 저장한다.
- LLM router 성공 결과는 `llm_audit[].routing_result`에도 저장한다.
- LLM 생성 score는 확률이 아니다. 모든 candidate의 유한한 0~1 score와 nonempty rationale을 요구한다. 빠진 score, NaN/범위 초과, 잘못된 specialty 등을 임의 교정하지 않는다. selected_specialty는 검증된 LLM 선택 필드를 사용한다.
- 실패는 `routing.status=failed`, selected_specialty=null, binding=null이다. Rule 재계산은 runtime 결과가 없는 구형 Rule 실행의 호환 경로에서만 가능하다.
- Offline LLM 조건은 **Router 호출 직전**에 멈춘다. 따라서 `status=stopped_before_model_call`, actual_llm_calls=0, specialty_boundary_reached=false다. 의도적 sentinel이 role_call 예외로 기록되어 routing.status=failed일 수 있지만 이는 실제 모델 생성 실패를 뜻하지 않는다. 이때 routing accuracy는 null이다.
- Offline Rule 조건은 Router가 결정적으로 실행되어 **specialty 호출 직전**까지 간다. 두 offline 경계 위치가 다름을 구분한다.
- `boundary_reached`는 router 또는 specialty 경계 도달이고 `specialty_boundary_reached`는 실제 specialty 경계 도달이다.
- Router trace의 memory_query/requested_selector/executed_selector는 null이다. candidate_specialties, router_uses_memory 및 제공된 retrieved_memory를 기록한다.
- 실제 live smoke가 정상 종료되지 않으면 전체 pilot 실행은 건너뛰고 smoke/validation 결과를 남긴다. 실패 상태로 전체를 성공한 것처럼 확장하지 않는다.

## 검증 결과

총 **36개 검사 통과**:

- primary router 통합 8개: 모의 응답 기반 두 LLM router의 실제 scheduler 경로, Rule 결과, memory 포함/제외, metadata allowlist, 명시적 실패, shared model binding, signature 구분, 세 CLI 조건의 JSON 파일 저장 및 router 이름 확인.
- Synthea v2 통합 8개.
- encounter pipeline 8개.
- mathematical alignment 12개.

추가로 syntax/import 및 CLI `--help`를 확인했다. 모의 응답 시험의 live=True는 요청 프록시 경로를 검사하기 위한 것이며 OllamaClient를 test double로 교체했다. 실제 모델 호출/성능 실험은 아니다. CLI 저장 검사도 작은 mock encounter를 사용하고 임시 출력만 생성했다.

```powershell
python -m unittest discover -s tests -p test_primary_router_integration.py
python -m unittest discover -s tests -p test_synthea_v2_integration.py
python -m unittest discover -s tests -p test_encounter_pipeline.py
python -m unittest discover -s tests -p test_mathematical_alignment.py
```

## 실행 명령

아래 명령은 실제 LLM 요청을 발생시킨다. 출력 경로가 이미 있으면 새 이름을 사용해야 한다. 추천 보고서는 기본 경로 `final_task_candidate_report_v2.md`에서 읽는다.

### Rule baseline

```powershell
python -m app.scripts.run_synthea_v2_pilot `
  --live `
  --primary-router rule_similarity `
  --registry app/data/synthea_v2/registry_shared_qwen.json `
  --context-chars 60000 `
  --memory-chars 30000 `
  --max-model-calls 16 --max-router-calls 8 --max-clinical-calls 8 `
  --output-dir outputs/routing_rule_02
```

### LLM Router

```powershell
python -m app.scripts.run_synthea_v2_pilot `
  --live `
  --primary-router llm `
  --registry app/data/synthea_v2/registry_shared_qwen.json `
  --context-chars 60000 `
  --memory-chars 30000 `
  --max-model-calls 16 --max-router-calls 8 --max-clinical-calls 8 `
  --output-dir outputs/routing_llm_02
```

### Memory-aware LLM Router

```powershell
python -m app.scripts.run_synthea_v2_pilot `
  --live `
  --primary-router memory_aware_llm `
  --registry app/data/synthea_v2/registry_shared_qwen.json `
  --context-chars 60000 `
  --memory-chars 30000 `
  --max-model-calls 16 --max-router-calls 8 --max-clinical-calls 8 `
  --output-dir outputs/routing_memory_llm_02
```

## 호환성과 남은 한계

기존 호출의 기본값은 rule_similarity다. 새 primary_router는 legacy routing_mode(consultation menu)와 별개의 설정이다. signature에 설정이 추가되므로 변경 전 checkpoint의 resume는 거절될 수 있다. 새 설정으로 실행하고 기존 결과와 섞어 재개하지 않는다.

현재 Full History는 사용자가 미리 추가한 budgeted_recent_history 동작을 유지한다. 이전 무축약 full history 실험과 조건이 다르므로 동일 baseline으로 혼합하지 않는다. 60,000자/30,000자는 문자 예산이며 모델 tokenizer/context window를 보장하지 않는다.

LLM Router는 primary decision 시점에 기존 성공 캐시를 확인하고 입력이 달라지면 모델을 호출하므로 Rule 대비 요청이 늘어날 수 있다. Router는 임상 결정 횟수 예산에서 제외한다. 요청 한도는 위의 총 16회/역할별 8회를 적용하며 교정 요청도 포함한다. 한도 소진이나 교정 후 반복 오류는 여전히 명시적 중단이다. Rule 대체는 하지 않는다. 이전 `_01`과 새 `_02`는 prompt/호출 예산/교정 정책이 달라 같은 실험 조건으로 합산하지 않는다.

작은 모델이 모든 후보 score를 올바른 JSON으로 반환하는지, 실제 모델 설치·서버 가용성·실험 정확도는 아직 live로 검증하지 않았다. 실패 시 failure_detail/router_audit를 먼저 확인한다. VoI 성능 평가 및 공식 Memory relevance 평가도 이번 범위에 포함하지 않았다.
