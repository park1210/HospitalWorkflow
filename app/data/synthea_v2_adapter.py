"""Allowlisted v2 projection into the existing encounter contract; no model rules."""
from copy import deepcopy
from datetime import timedelta
import json
import math

from app.agents.patient_agent import PatientAgent
from app.core.clinical_observation import prepare_encounter
from app.core.longitudinal_memory import timestamp


QUESTIONS = ("What symptoms are you experiencing?", "What allergies have you been told about?",
             "What medications do you know you take?", "What medical history do you know about?")


def available_time(value):
    # Date-only record: upper bound of the entire day, not an invented occurrence.
    return timestamp(value + "T00:00:00Z") + timedelta(days=1) if len(value) == 10 else timestamp(value)


def patient_input(source):
    state = source["patient_visible_state_v2"]
    cutoff = timestamp(source["index_encounter"]["start_time"])
    symptoms = []
    for s in state["current_symptoms"]:
        if timestamp(s["symptom_timestamp"]) > cutoff:
            raise ValueError("Future symptom in initial patient input")
        symptoms.append({"id": s["provenance_id"], "symptom_name": s["symptom_name"]})
    result = {"age": source["patient"].get("age_at_index_encounter"),
              "sex": source["patient"].get("gender"), "current_symptoms": symptoms}
    for key in ("known_allergies", "known_medications", "known_history"):
        result[key] = []
        for fact in state.get(key, []):
            if available_time(fact["source_timestamp"]) >= cutoff:
                continue
            # Names only: never interpret reactions as current symptoms or a chart prescription as use.
            text = fact.get("source_description")
            if text:
                result[key].append({"id": fact["fact_id"], "text": text})
    return result


def convert_case(source):
    index = source["index_encounter"]
    start, visit = index["start_time"], index["encounter_id"]
    cutoff = timestamp(start)
    if timestamp(index["decision_time"]) != cutoff:
        raise ValueError("This pilot requires decision time equal to encounter start")
    patient_id = source["patient"]["patient_id"]
    visible = patient_input(source)
    patient = PatientAgent({"synthea_v2_patient_input": visible})
    trace = patient.initial_utterance()
    history, excluded = [], []
    for past in source["past_visits"]:
        if past["encounter_id"] == visit or timestamp(past["start_time"]) >= cutoff:
            raise ValueError("Non-past visit in past_visits")
        records = []
        for record in past["records"]:
            available = available_time(record["timestamp"])
            # For date-only observations in this encounter, encounter start is a lower bound.
            available = max(available, timestamp(past["start_time"]))
            if available >= cutoff or not record["normalized_text"].strip():
                excluded.append(record["record_id"])
                continue
            records.append({"memory_id": past["encounter_id"] + ":" + record["record_id"],
                            "patient_id": patient_id, "visit_id": past["encounter_id"],
                            "visit_started_at": past["start_time"], "observed_at": available.isoformat(),
                            "available_at": available.isoformat(), "source_id": record["record_id"],
                            "kind": "history", "text": record["normalized_text"], "supersedes": []})
        history.append({"visit_id": past["encounter_id"], "started_at": past["start_time"], "records": records})
    events = [{"event_id": "patient-question:" + str(i), "action": "Ask", "target": q,
               "available_minute": 0, "evidence": patient.answer_v2(q)["utterance"]}
              for i, q in enumerate(QUESTIONS)]
    for event in source["environment"]["source_event_store"]:
        if event["action_type_candidate"] != "Test" or event["timing_precision"] != "datetime" or not event["evidence"]:
            continue
        minute = math.ceil((timestamp(event["timestamp"]) - cutoff).total_seconds() / 60)
        if minute < 0:
            continue
        target = event["target"]
        name = target.get("description") or target.get("acquisition_metadata", {}).get("MODALITY_DESCRIPTION")
        if not name:
            raise ValueError("Test has no source-backed display name")
        events.append({"event_id": event["event_id"], "action": "Test",
                       "target": name + " [" + event["event_id"] + "]",
                       "available_minute": minute, "evidence": json.dumps(event["evidence"], ensure_ascii=False)})
    initial = source["initial_clinical_state"]
    objective = initial["safe_initial_objective_observations"] + initial["safe_initial_vitals"]
    if any(available_time(r["timestamp"]) > cutoff for r in objective):
        raise ValueError("Unreleased initial clinical evidence")
    case = {"case_id": source["case_id"], "index_encounter_id": visit, "index_encounter_start": start,
            "longitudinal": {"patient_id": patient_id}, "past_visits": history,
            "current_initial_state": {
                "doctor_visible_info": {"chief_complaint": trace["utterance"],
                    "demographics": {"age": initial.get("age_at_index_encounter"), "sex": initial.get("gender")},
                    "arrival_info": {"encounter_class": initial["encounter_class"]}, "initial_vitals": {}},
                "patient_visible_info": {"chief_complaint": trace["utterance"]}},
            "synthea_v2_patient_input": visible,
            "synthea_v2_initial_evidence": [r["normalized_text"] for r in objective],
            "current_encounter_events": events}
    # Keep all source history outside role projections; exclude only temporally unsafe runtime records.
    case["source_past_visits"] = deepcopy(source["past_visits"])
    case["synthea_v2_excluded_memory_ids"] = excluded
    return prepare_encounter(case), trace
