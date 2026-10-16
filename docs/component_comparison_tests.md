# 실행 중 병행 가능한 추가 검사와 남은 작업

## 이번 구현

두 비교 도구는 저장 파일만 읽으며 Ollama/OpenAI 요청을 하지 않는다. 실행 중인 실험의 입력·결과 파일도 수정하지 않는다. 결과는 항상 새 폴더에 저장한다.

### 7번: 검색 방식 비교

`app/scripts/compare_memory_retrieval.py`는 No Memory / Full History / lexical top-k / 저장된 벡터 top-k를 같은 방문·라벨로 비교한다. Precision/Recall/stale 검색률, coverage, 검색 ID, 충돌 후보 수와 입력 해시를 저장한다. 벡터의 질의·기억 텍스트 해시가 맞지 않으면 거부하며, 검색 결과의 환자·방문·시간 경계를 검사한다.

```powershell
python -m app.scripts.compare_memory_retrieval --cases app/data/challenge_v1/cases_validation.json --memory app/data/challenge_v1/memory.json --annotations app/data/challenge_v1/annotations_validation.json --scenarios app/data/challenge_v1/scenarios.json --top-k 1 3 --output-dir outputs/memory_compare_01
```

이번 저장 결과: `outputs/memory_comparison_ready_01/`. 실제 벡터가 없는 lexical 기준선 결과다. `lexical-hash-256` 벡터를 넣으면 `lexical_hash_vectors`라고 표시하며 임베딩 모델의 의미 검색이라고 표기하지 않는다.

### 실제 임베딩 비교 — 현재 LLM 실행 종료 후

아래 첫 명령은 Ollama를 사용한다. 현재 진료 실험과 동시에 실행하지 않는 것을 권한다. embeddinggemma가 설치되어 있어야 한다. `local-unverified`는 버전 미확인 표시이며 논문용 실행에서는 설치 모델의 실제 digest를 확인해 revision으로 기록한다.

```powershell
python -m app.scripts.build_memory_embeddings --memory app/data/challenge_v1/memory.json --cases app/data/challenge_v1/cases_validation.json --model embeddinggemma --revision local-unverified --endpoint http://localhost:11434 --output outputs/challenge_validation_vectors_01.json

python -m app.scripts.compare_memory_retrieval --cases app/data/challenge_v1/cases_validation.json --memory app/data/challenge_v1/memory.json --annotations app/data/challenge_v1/annotations_validation.json --scenarios app/data/challenge_v1/scenarios.json --embeddings outputs/challenge_validation_vectors_01.json --top-k 1 3 --paper-plan app/data/challenge_v1/plan_validation.json --output-dir outputs/memory_semantic_01
```

두 번째 명령은 모델 호출이 없다. `comparison.md`, `summary.csv`, `comparison.json`과 semantic 실행용 `plan_semantic.json`을 만든다. 원래 plan의 사례·기억·라벨과 비교 입력이 일치해야 한다. 나머지 설정은 유지하고 검색 방식/벡터만 변경한다. 새 plan에는 같은 컴퓨터의 절대 입력 경로가 저장된다.

```powershell
python -m app.scripts.run_paper_experiments --plan outputs/memory_semantic_01/plan_semantic.json --execute --output-dir outputs/challenge_semantic_01
```

semantic이라고 성능 향상을 보장하지 않는다. 특히 top-k와 질의 표현에 따라 무관한 기억이 더 많이 검색될 수도 있다. 검증 세트에서 설정을 정한 후 별도 test 벡터를 생성해 평가한다.

### 9번: 라우팅 기준선 비교

`app/scripts/compare_routing_baselines.py`는 저장된 동일 관측의 전문과 응답으로 rule / seeded random / adaptive를 비교한다. Oracle 효용은 모든 후보의 사후 결과 중 최대값이며 실행 정책에 전달하지 않는다. 출력에는 regret, coverage, 선택 정답률, 라우팅 근거가 포함된다.

```powershell
python -m app.scripts.compare_routing_baselines --outcomes app/data/research_synthetic_v1/routing_test_bounded.json --registry app/data/research_synthetic_v1/registry_local.json --utility app/data/research_synthetic_v1/routing_utility_bounded.json --seeds 0 1 2 --output-dir outputs/router_compare_01
```

이번 결과는 `outputs/routing_comparison_ready_01/`이다. 기존 toy 전문과 응답을 재평가한 결과이며 새로운 임상 자료가 아니다. 이 자료는 전문과들이 모두 정답이라 regret 차이가 주로 지연 가중치에서 나온다. 새 실제 LLM 응답 수집에는 기존 `collect_routing_outcomes`를 사용한다. [수집 안내](research_7_9_completion.md)

모델/버전 불일치, 학습 환자 중복, 동일 관측 불일치, duplicate, validation/test 혼합을 거부한다. 후보 응답·비용 누락이나 기권은 전체 mean regret를 NA로 유지한다. random seed 3개는 독립 환자 표본 3개가 아니다.

## 현재 사용자가 실행한 실험 확인

확인 시점 `outputs/challenge_validation_01/`에는 B4까지 결과가 저장되어 있었다. B0/B1/B2/B4는 완료, B3는 마지막 `challenge-validation-paraphrase/v2`에서 실패했다. 원인은 JSON 잘림이 아니라 `schema_validation: Unavailable department`였다. 응답 종료는 stop, 출력은 75토큰이었다.

`HospitalLLMPolicy._decision`의 생성 스키마를 행동별로 나누어 request_test/consult_specialty/treat의 target을 실제 허용 목록 enum으로 제한했다. 질문은 물음표 종결 패턴을 추가했다. 추가 재시도나 LLM 호출은 없으며, 잘못된 대상을 다른 전문과로 조용히 바꾸지 않는다. 기존 결과는 보존했다. 호출 없는 실제 스케줄러 테스트로 허용 전문과 enum을 확인했으며 **이 수정 후 실제 B3 재실행은 아직 하지 않았다.**

```powershell
python -m app.scripts.run_paper_experiments --plan app/data/challenge_v1/plan_validation.json --execute --conditions B3 --output-dir outputs/challenge_b3_fixed_01
```

이는 수정 확인용이다. 최종 논문 비교는 변경된 스키마를 모든 조건에 적용한 새 B0~B4 실행으로 맞춘다. 서로 다른 코드 버전의 결과를 동일 설정 반복처럼 합치지 않는다.

## 얼마나 남았는가

UI 이전 연구 파일럿을 다음 네 작업으로 정리한다. 남은 시간을 정확히 추정할 실행 표본은 부족하며, 데이터 검수 시간도 포함되지 않았다.

| 남은 작업 | 구현 상태 | 실행/자료 상태 |
|---|---|---|
| 1. B3 허용 전문과 수정 확인 | 스키마 수정·오프라인 검사 완료 | 실제 B3 재실행 필요 |
| 2. 실제 임베딩 대 lexical 비교 | 비교·semantic plan 생성 도구 완료 | 새 challenge 벡터 생성·실험 필요 |
| 3. 전문과별 유용성 검증 | 수집·fit·기준선/regret 비교 도구 완료 | 전문과에 따라 성능이 갈리는 자료와 응답 필요 |
| 4. 설정 고정 후 B0~B4 반복·held-out 평가 | 실행·집계 도구 완료 | 앞 단계 완료 후 전체 반복 실험 필요 |

임상 검수 데이터, 실행별 stale 오용 검수, VoI 확률/비용 타당성 검증은 이 네 파일럿 작업과 별도로 남아 있다. 코드 완료율을 임상 연구 완료율로 환산하지 않는다. 새 UI는 이 이후 작업이며 아직 구현하지 않았다.

이번 최소 검사: 새 비교 도구 검사 2개 + 출력 계약/정보 경계 검사 2개 통과. 질의 벡터 불일치, 비용 누락, 학습 환자 겹침을 검증했다. 이 턴에서는 새 LLM/임베딩 호출을 하지 않았다.
