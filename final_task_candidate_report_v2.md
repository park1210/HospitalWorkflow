# Episode presentation 기준 최종 Task 추천 v2

같은 episode로 연결된 방문 전 증상을 포함해 새 60개 case에서 task 후보를 다시 계산했다. 증상 source의 status는 CURRENT_SUPPORTED를 유지하며 현재 presentation에 사용할 수 있도록 정책 승인했다.

## memory

최종 후보 9개, 추천 9개, 목표 10개 대비 부족 1개.

| 순위 | case_id | specialty | symptom | past visit | future laboratory 값 | laboratory 시각 수 |
|---:|---|---|---:|---:|---:|---:|
| 1 | symptom-v1-81b56520-bf9a-2eb4-8496-253bebaec655 | otolaryngology | 9 | 143 | 0 | 0 |
| 2 | symptom-v1-8e104f54-374a-19c5-6a62-633bb803f77f | otolaryngology | 9 | 116 | 0 | 0 |
| 3 | symptom-v1-1274d9e0-62c8-6396-8ebb-a82d8b00e92f | otolaryngology | 9 | 189 | 0 | 0 |
| 4 | symptom-v1-4e4770b5-890d-715a-ec0b-0ac5343981c6 | otolaryngology | 9 | 93 | 0 | 0 |
| 5 | symptom-v1-1c3d62b6-b759-90c5-da86-503ab0777fe8 | otolaryngology | 9 | 80 | 0 | 0 |
| 6 | symptom-v1-96f0ec93-fcaa-6f3d-44a0-4aa1c1649c9e | otolaryngology | 9 | 117 | 0 | 0 |
| 7 | symptom-v1-928ce4e7-8296-4099-2374-d6320a266e3f | otolaryngology | 9 | 48 | 0 | 0 |
| 8 | symptom-v1-ddf91fab-f4b9-dc35-c903-6c623d2d5b93 | gastroenterology | 4 | 134 | 0 | 0 |
| 9 | symptom-v1-092ecc37-0e40-d4b0-f6ff-8c5ed33e5ffa | gastroenterology | 4 | 83 | 0 | 0 |

## routing

최종 후보 59개, 추천 10개, 목표 10개 대비 부족 0개.

| 순위 | case_id | specialty | symptom | past visit | future laboratory 값 | laboratory 시각 수 |
|---:|---|---|---:|---:|---:|---:|
| 1 | symptom-v1-feea9927-4293-bc17-50a2-d3cdf5bcdcca | otolaryngology | 9 | 220 | 0 | 0 |
| 2 | symptom-v1-716fe0ad-8102-6db4-bb9e-d2eb2bdded6d | surgery | 7 | 78 | 0 | 0 |
| 3 | symptom-v1-ddf91fab-f4b9-dc35-c903-6c623d2d5b93 | gastroenterology | 4 | 134 | 0 | 0 |
| 4 | symptom-v1-0f563ce2-9557-048b-ecb6-3917532b14d2 | otolaryngology | 9 | 190 | 0 | 0 |
| 5 | symptom-v1-1274d9e0-62c8-6396-8ebb-a82d8b00e92f | otolaryngology | 9 | 189 | 0 | 0 |
| 6 | symptom-v1-cf1b4463-a906-5fe5-58b2-9e930d6a4b65 | otolaryngology | 9 | 166 | 0 | 0 |
| 7 | symptom-v1-13be8b8f-17f9-be40-5db6-7e21986b2a39 | otolaryngology | 9 | 162 | 0 | 0 |
| 8 | symptom-v1-81b56520-bf9a-2eb4-a632-70e2460b0be6 | otolaryngology | 9 | 154 | 0 | 0 |
| 9 | symptom-v1-f401ed9d-b066-35c4-10e2-cfe93b22ec13 | otolaryngology | 9 | 130 | 0 | 0 |
| 10 | symptom-v1-a8c52638-11ee-4d25-1a5a-26a155934a1f | otolaryngology | 9 | 126 | 0 | 0 |

추천 specialty 3종. 현재 episode 연결 근거가 있는 모집단의 specialty 범위 안에서만 다양성을 확보했다.

## voi

최종 후보 0개, 추천 0개, 목표 10개 대비 부족 10개.

| 순위 | case_id | specialty | symptom | past visit | future laboratory 값 | laboratory 시각 수 |
|---:|---|---|---:|---:|---:|---:|

추천 없음. 부족한 source/timing 조건을 임의 보완하지 않았다.

Memory의 relevant/noisy 구분은 code overlap proxy이며 검수된 relevance label이 아니다. VoI gold action/likelihood는 생성하지 않았고 outcome_model은 null이다. 이전의 498개 모집단 ranking을 덮어쓰지 않았다.
