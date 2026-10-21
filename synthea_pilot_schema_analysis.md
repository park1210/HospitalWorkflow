# Synthea pilot 실제 스키마 분석

요청 이름은 `pilot_base_cases(1).jsonl`이나 접근 가능한 실제 파일은 프로젝트 최상위의 `pilot_base_cases.jsonl`이다. 두 파일의 동일성은 확인되지 않았다. 실제 읽은 파일의 hash를 기록한다.

모든 15개 case에 아래 13개 필드가 존재한다. demographics, chief_complaint, current_initial_state는 원본에 없다. task_eligibility/annotation_metadata는 평가용이다.

past_visits: encounter_id/start_time/stop_time/encounter_class/code/description/events.

event: event_id/event_type/event_time/time_precision/data/source_file/source_row_number.

events의 observations는 description/value/units/category/code 등을 담고, procedures는 수행 기록이며 정상/비정상 판독문을 보장하지 않는다. imaging_studies는 영상 획득 메타데이터다. 원본에 Ask/Consult 형태의 환자 응답이나 전문의 의견은 없다.

```json
{
  "source": "pilot_base_cases.jsonl",
  "sha256": "2fb223716a62f9206ca09272960e0971312c31e8138c05adaba95f83ec4d77cc",
  "cases": 15,
  "fields": {
    "case_id": 15,
    "patient_id": 15,
    "index_encounter_id": 15,
    "index_encounter_start": 15,
    "index_encounter_class": 15,
    "gold_condition_code": 15,
    "gold_condition_description": 15,
    "primary_specialty": 15,
    "acceptable_specialties": 15,
    "past_visits": 15,
    "current_encounter_events": 15,
    "task_eligibility": 15,
    "annotation_metadata": 15
  },
  "specialties": {
    "cardiology": 2,
    "neurology": 2,
    "pulmonology": 2,
    "endocrinology": 2,
    "surgery": 2,
    "infectious_disease": 3,
    "gastroenterology": 1,
    "ophthalmology": 1
  },
  "current_types": {
    "procedures": 78,
    "medications": 71,
    "observations": 608,
    "careplans": 7,
    "immunizations": 5,
    "supplies": 70,
    "devices": 18,
    "imaging_studies": 3
  },
  "current_precision": {
    "datetime": 783,
    "date": 77
  },
  "past_visits": 1855,
  "past_events": 25681
}
```
