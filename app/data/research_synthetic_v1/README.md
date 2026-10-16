# 합성 연구 점검 자료

**임상 미검수. 실제 환자 자료가 아니다.** 6명·12방문, 환자 단위 train/validation/test 분할과 생성 규칙 기반 라벨을 포함한다.

`embeddings_semantic.json`은 로컬 embeddinggemma의 실제 768차원 산출물이다. `embeddings_lexical.json`은 해시 단어 벡터 기준선이다. 두 파일은 서로 다른 검색 조건이다.

`registry_local.json`의 버전은 생성 시 조회한 설치 모델 digest다. `prices_local_api_only.json`은 로컬 API 요금만 0으로 선언하며 총 운영 비용을 뜻하지 않는다.

`routing_train_observed.json`은 GPU 경로 시간 초과 기록, `routing_train_cpu.json`은 CPU 호출의 응답 길이 초과/JSON 검증 실패 기록이다. `routing_utility_smoke.json`은 그 실패 결과를 학습한 소프트웨어 점검 산출물이므로 유용한 임상 라우터로 사용하지 않는다. 이후 bounded 산출물도 합성 과제의 결과이며 별도 평가가 필요하다.

전체 입력 형식·명령·한계는 [추가 구현 안내](../../../docs/research_7_9_completion.md)를 참조한다.

길이를 제한한 구조화 출력 적용 후 `routing_train_bounded.json` 4회와 `routing_test_bounded.json` 4회는 정상 처리됐다. `routing_utility_bounded.json`은 전자로 학습했고 `routing_regret_smoke.json`은 후자의 별도 환자 평가다. Regret 0/coverage 1은 동일한 단순 근거 부족 과제의 결과이며 임상 일반화나 전문 모델 우열을 뜻하지 않는다. 지연은 CPU·로딩·캐시 조건에 의존한다.
