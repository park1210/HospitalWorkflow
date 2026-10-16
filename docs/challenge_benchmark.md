# 다음 단계: 유형별 합성 도전 실험

## 구현과 목적

기존 두 방문은 모든 조건이 검사 한 번으로 확진하는 경로라 기억·검색 차이를 확인하기 어렵다. `app/scripts/prepare_challenge_benchmark.py`는 **12명 × 2방문 = 24방문**, 환자별 이전 기록과 검증용 미래 기록을 생성한다. train/validation/test는 각각 다른 4명·8방문이다. 고정된 합성 방문 기록이며 앞선 방문을 실제 LLM으로 실행해 만든 기록은 아니다.

| 유형 | 목적 |
|---|---|
| distractors | 관련 기억 1개와 무관한 기록 3개를 구별하는지 |
| superseded | 첫 방문 이후 갱신된 기록을 다음 방문에 사용하고 대체된 기록을 제외하는지 |
| conflict | 긍정·부정 기록을 모두 찾아 검토 후보를 남길 수 있는지 |
| paraphrase | 질의와 관련 기록의 단어가 다를 때 lexical 검색이 누락하는지 |

현재 `app/data/challenge_v1/`에 생성되어 있다. 출처·미검수 상태는 `provenance.json`, 정답·관련성·stale 라벨은 각 split 파일, 유형은 `scenarios.json`에 있다. 유형/라벨은 평가 전용이며 모델 관측에 추가하지 않는다. 이전 지표는 현재 진단과 불일치할 수도 있게 구성했다. 모든 모형 확률·비용은 가정값이며 이 데이터에 맞춰 보정된 임상 값이 아니다.

## 실행 순서

### 1. 데이터와 실행 계획 확인 (호출 없음)

```powershell
python -m app.scripts.run_paper_experiments --plan app/data/challenge_v1/plan_validation.json
```

데이터 자체를 다시 생성하려면 새 폴더를 지정한다.

```powershell
python -m app.scripts.prepare_challenge_benchmark --output-dir outputs/challenge_generated_02
```

생성 시 환자 split 분리, 환자/방문/공개시각 경계, relevance/stale 라벨 유효성을 확인한다. 네 검색 설정 × 24방문 = 96회 검색 감사 결과가 `memory_audit.json`, 요약이 생성 폴더 `README.md`에 저장된다. 검색 결과를 모델에 전달하기 전의 검색기 자체 평가이며 B4에서 기억을 실제 조회했는지와 구분한다.

### 2. 비용 민감도 확인 (호출 차단)

```powershell
python -m app.scripts.run_paper_experiments --plan app/data/challenge_v1/plan_validation_costly.json --execute --offline --conditions B4 --output-dir outputs/challenge_offline_01
```

비용 조건은 검사 0.4, 문진/협진 1.0, 기억 조회 0.01이다. 기본 조건은 기존 모형 그대로다. 검사 가격만의 효과가 아니라 여러 행동 비용을 바꾼 시나리오다. 모형이 지원하지 않는 응답이나 LLM fallback이 필요해지면 offline 실행은 실패를 기록한다.

### 3. 검증 세트 실제 B0~B4 파일럿

```powershell
python -m app.scripts.run_paper_experiments --plan app/data/challenge_v1/plan_validation.json --execute --output-dir outputs/challenge_validation_01
```

8방문 × 5조건 = 40 방문 실행이다. Ollama와 registry에 명시된 모델이 필요하다. 검증 세트에서 실행 오류와 명칭 규약을 확인하고 top-k·모형 비용·검색 방법을 결정한다. 반복은 `--repeats 3`처럼 지정한다. 기본 1회는 신속한 파일럿용이며 성능 입증에 충분한 반복 수라는 뜻은 아니다.

### 4. 설정을 고정한 뒤 test

```powershell
python -m app.scripts.run_paper_experiments --plan app/data/challenge_v1/plan_test.json --execute --output-dir outputs/challenge_test_01
```

test 결과를 보고 최적 설정을 고르면 안 된다. generator의 test 검색 감사는 미리 설계한 스트레스 조건의 동작 확인이며 이를 독립적인 임상 검증으로 주장하지 않는다. 데이터가 작고 의도적으로 만들어졌으므로 논문의 최종 성능 근거는 별도 검수 자료가 필요하다.

## 결과에서 먼저 볼 것

- `paper_results.md`: 전체 성능·실패 현황.
- `stratified_table.csv`: distractors/superseded/conflict/paraphrase별 성능과 coverage. 전체 평균에 가려진 실패 확인.
- `episodes.csv`: 유형별로 어떤 환자 방문이 실패·미완료·오답이었는지 확인.
- `B*_r*.report.json`: 모델/VoI의 행동 이유와 memory/route 선택.

현재 검색 감사에서는 distractors의 full-history precision 0.25, selective precision 1.0이었다. 그러나 conflict에서 top-k=1 recall은 1/3, top-k=3은 1이고, paraphrase의 lexical recall은 0이었다. 이는 **생성 규칙에 따른 기능 점검**이며 일반 검색 성능 추정이 아니다. conflict 관련성은 지표 기록 + 양쪽 진술 세 개를 관련 기록으로 정의했다. Full History의 stale 포함은 설계된 기준선 동작이며 곧 오용을 뜻하지 않는다.

이번 실행에서는 비용 변경 validation B4 8방문을 모델 호출 없이 완료했다. 실제 LLM 40방문 실험은 아직 수행하지 않았다.

## 아직 필요한 것

1. **7번**: 실제 임베딩으로 paraphrase 검색을 비교. 기존 `build_memory_embeddings` 도구를 이용해 동일 자료의 벡터를 만들고 plan의 retrieved_mode를 semantic으로 바꿀 수 있다. 현재 bundle은 벡터를 생성하지 않았다.
2. **9번**: 전문과에 따라 성능이 달라지는 별도 probe와 후보별 응답 수집. 현재 plan은 이전 toy-probe 라우터를 재사용하며 전문과 최적화가 검증된 데이터셋이 아니다. train split을 만들었다고 라우터를 재학습한 것은 아니다.
3. **10번**: 객관적 검사 하나로 확진되지 않는 모형, 다양한 결과 likelihood·비용 검수. 현재 진단 후보는 두 개이고 확정 검사 T가 그대로 있어 B4 정확도 우위를 주장할 수 없다.
4. 실제 임상 검수와 실행별 stale misuse 라벨. 자동으로 임상 검수를 완료한 것으로 표시하지 않는다.

새 UI에 연결할 데이터는 `results.json.stratified_table`과 `episodes.csv`의 `scenario_group`으로 준비했다.
