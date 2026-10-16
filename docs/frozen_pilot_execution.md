# 실제 모델 기반 후속 연구 파일럿

## 실행 범위

1. 사용자 B3 재실행 확인: `outputs/challenge_b3_fixed_01/`, 8방문 완료, 호출 실패 0, 진단 정답 7/8.
2. 실제 `embeddinggemma:latest` 벡터 생성 및 validation 검색 비교.
3. 신경과/호흡기과의 동일 관측 단서 평가 24호출, train/validation/test 별도 환자 ID.
4. 검색 설정 고정 후 장기 기억 validation 1회, test 3회 B0~B4 비교.

모든 데이터는 합성·미검수이다. 단서 평가와 장기 기억 A/B 진단은 서로 다른 과제이므로 라우터를 무조건 전이하지 않는다.

## 임베딩 결과와 설정 고정

모델 digest: `85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1`.

`outputs/memory_semantic_01/comparison.json`에서 validation 전체 Recall은 lexical k=1의 0.5833에서 실제 벡터 k=1의 0.8333으로 변했다. k=1의 검색된 기록 Precision은 양쪽 모두 1.0이지만 lexical은 일부 방문에서 검색이 없어 precision coverage가 다르다. 벡터 k=3은 Recall 1.0, Precision 0.5였다. 검색 정보량과 precision을 고려해 **semantic k=1**을 선택했고, 충돌 사례에서 recall 1/3인 한계를 유지한다.

`outputs/frozen_protocol_01/protocol.json`에 test 실행 전 선택 근거·반복 수·비용·모형·해석 규칙을 기록했다. test 자료로 top-k를 다시 고르지 않았다. 비교는 환자/방문/공개시각 경계를 유지하고 정답 라벨을 임베딩 입력에 보내지 않는다.

## 전문과 평가

`app/scripts/run_specialty_pilot.py`는 기존 프로젝트의 `high_signal_diagnosis_rules.json`, `evidence_diagnosis_hints.json`에서 단서를 가져온다. 4개 진단은 Myasthenia gravis, BPPV, Tuberculosis, NRDS이다. 각 split에서 단서의 표현·순서를 바꾸고 다른 환자 ID를 부여한다. **실제 환자 기록이나 임상 전문가 작성 시나리오가 아니다.** 같은 질환 단서 템플릿을 공유하므로 독립적인 임상 일반화 평가가 아니다.

두 전문과에 같은 관측과 전체 진단 후보 목록을 제공한다. 환자별 정답은 평가에만 사용하며 CPU-only native Ollama 요청을 순차 실행한다. 각 응답 후 checkpoint를 저장하고, 출력 종료 이유·사용량을 보존한다. weights=(accuracy 1, cost 0, latency .001)은 test 결과를 보기 전에 고정했다. 학습은 train 응답만 사용한다.

```powershell
python -m app.scripts.run_specialty_pilot --execute --output-dir outputs/specialty_cue_pilot_02
```

기존 실행: `outputs/specialty_cue_pilot_01/`. 모든 24호출 성공. test 4사례에서 신경과 4/4, 호흡기과 3/4. Adaptive 선택은 4/4, 평균 regret 약 0.00009775였다. 표본이 매우 작고 지연은 로딩/CPU 환경에 영향을 받으므로 전문과 우월성으로 일반화하지 않는다. 기존 registry의 rule 키워드는 이전 synthetic 과제용이므로 이 단서 과제에서 rule coverage는 0이었다. 이를 rule 대비 성능 향상이라고 주장하지 않는다. Random 일부 seed도 4/4였으며 통계적 우월성을 입증하지 않는다.

## 고정 B0~B4 실행

```powershell
python -m app.scripts.run_frozen_challenge --protocol outputs/frozen_protocol_01/protocol.json --validation-embeddings outputs/challenge_validation_vectors_01.json --execute --output-dir outputs/frozen_challenge_02
```

실행기는 설치 모델 digest를 확인하고 시험 세트 임베딩을 만든다. 이어서 validation 8방문×5조건×1회와 test 8방문×5조건×3회를 순차 실행한다. 새 output 폴더만 허용한다. 모델 호출 URL은 해당 로컬 endpoint로 지정하며 temperature 0.2, 최대 출력 768, 시간 한도 30, 자동 재시도 0으로 고정한다. 기본 합성 VoI 모형과 기존 toy-domain router를 유지한다. 첫 실행 경로는 `outputs/frozen_challenge_01/`이다.

조건 실패가 있어도 다음 조건으로 진행하며 실패를 지우지 않는다. 반복 번호는 decoder seed가 아니다. test 독립 환자는 4명이고 반복 3회가 환자를 12명으로 늘리지 않는다. 모든 최종 조건의 코드/입력 해시와 설정은 각 manifest에 저장된다. 이 실행기는 자동 재개를 제공하지 않는다.

## 통합 보고서

모든 계획된 조건이 저장된 뒤에만 다음 명령으로 정리한다.

```powershell
python -m app.scripts.summarize_research_pilot --longitudinal-dir outputs/frozen_challenge_01/test --memory-validation outputs/memory_semantic_01/comparison.json --memory-test outputs/frozen_challenge_01/memory_test/comparison.json --specialty-dir outputs/specialty_cue_pilot_01 --output-dir outputs/research_pilot_summary_01
```

보고서의 세 표는 서로 다른 측면을 측정한다. 임베딩 검색 지표, 전문과 단서 과제 결과, 장기 기억 합성 A/B 진단 반복 결과를 하나의 임상 신뢰성 점수로 합치지 않는다. 실패/미실행을 포함한 정답률과 완료 방문 정답률을 함께 제시하고 NA 지표를 0으로 바꾸지 않는다.

남은 연구 한계는 자연스러운 다회 방문 임상 시나리오·전문가 검수, specialty-sensitive 시나리오의 본 엔진 통합, 임상 비용/확률 보정, 충분한 독립 환자 수다.
