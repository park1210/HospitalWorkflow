"""Explicit role projections: never send the complete case to a model."""
from copy import deepcopy


def prepare_encounter(case):
    """Adapt opt-in encounter data to the existing runtime, without exposing events."""
    if "index_encounter_id" not in case:
        return deepcopy(case)
    from app.core.longitudinal_memory import timestamp, PatientMemoryStore
    result = deepcopy(case)
    identity = result.get("longitudinal", {})
    visit, start = result["index_encounter_id"], result["index_encounter_start"]
    if not isinstance(visit, str) or not visit.strip() or not identity.get("patient_id"):
        raise ValueError("Encounter needs an ID and longitudinal.patient_id")
    cutoff = timestamp(start)
    if identity.get("visit_id", visit) != visit or identity.get("started_at", start) != start:
        raise ValueError("Encounter and longitudinal identifiers disagree")
    result["longitudinal"] = dict(patient_id=identity["patient_id"], visit_id=visit, started_at=start)
    result.setdefault("case_id", f"{identity['patient_id']}-{visit}")
    initial = result["current_initial_state"]
    if not isinstance(initial, dict) or set(initial) - {"doctor_visible_info", "patient_visible_info"}:
        raise ValueError("Initial state allows only doctor_visible_info and patient_visible_info")
    doctor = initial.get("doctor_visible_info", {})
    patient = initial.get("patient_visible_info", {})
    if not isinstance(doctor, dict) or set(doctor) - {"chief_complaint", "demographics", "arrival_info", "initial_vitals"}:
        raise ValueError("Unexpected initial doctor fields")
    allowed_patient = {"chief_complaint", "history", "associated_symptoms", "past_medical_history",
                       "medications", "allergies", "social_history", "age", "sex"}
    if not isinstance(patient, dict) or set(patient) - allowed_patient:
        raise ValueError("Unexpected initial patient fields")
    result["doctor_visible_info"], result["patient_visible_info"] = deepcopy(doctor), deepcopy(patient)
    # Disable legacy result and progression sources in this strict event contract.
    result["hidden_test_results"] = {}
    result["temporal_profile"] = {"arrival_time_min": 0}
    result.pop("test_access", None)
    records = []
    for past in result["past_visits"]:
        if past["visit_id"] == visit or timestamp(past["started_at"]) >= cutoff:
            raise ValueError("past_visits must precede the index encounter")
        for record in past["records"]:
            if (record["patient_id"] != identity["patient_id"] or record["visit_id"] != past["visit_id"]
                    or timestamp(record["visit_started_at"]) != timestamp(past["started_at"])
                    or timestamp(record["available_at"]) > cutoff):
                raise ValueError("Past record crosses patient/encounter boundary")
            records.append(record)
    PatientMemoryStore(records)
    events, seen = result["current_encounter_events"], set()
    if not isinstance(events, list):
        raise ValueError("current_encounter_events must be a list")
    for event in events:
        if set(event) != {"event_id", "action", "target", "available_minute", "evidence"}:
            raise ValueError("Event fields: event_id, action, target, available_minute, evidence")
        if event["action"] not in {"Ask", "Test", "Consult"}:
            raise ValueError("Unsupported event action")
        if any(not isinstance(event[k], str) or not event[k].strip() for k in ("event_id", "target", "evidence")):
            raise ValueError("Event strings must be nonempty")
        if type(event["available_minute"]) is not int or event["available_minute"] < 0:
            raise ValueError("Event time must be nonnegative integer minutes")
        key = (event["action"], event["target"])
        if event["event_id"] in seen or key in seen:
            raise ValueError("Duplicate event ID or action target")
        seen.update((event["event_id"], key))
        if event["action"] == "Ask" and not event["target"].endswith("?"):
            raise ValueError("Ask targets must be explicit questions ending in '?'")
        if event["action"] == "Consult":
            from app.utils.department_catalog import SUPPORTED_DEPARTMENTS
            if event["target"] not in SUPPORTED_DEPARTMENTS:
                raise ValueError("Consult target must use the department catalog")
    result["available_tests"] = [e["target"] for e in events if e["action"] == "Test"]
    return result


def encounter_evidence(runtime, action, target):
    """Return only released source evidence; never generate a missing answer."""
    for event in runtime.case_data.get("current_encounter_events", []):
        if (event["action"] == action and event["target"] == target
                and event["available_minute"] <= runtime.current_time_min):
            return deepcopy(event)
    return None


def memory_query(observed):
    """Deterministic query expansion using public state only; same retrieval algorithms."""
    import json
    fields = ("chief_complaint", "current_symptoms", "vital_signs", "history",
              "objective_findings", "consults", "working_assessment")
    return "\n".join(f"{key}: " + (value if isinstance(value, str) else
                    json.dumps(value, ensure_ascii=False, sort_keys=True))
                    for key in fields if (value := observed.get(key)))


def initial_symptoms(case):
    info = case.get("patient_visible_info", {})
    nested = info.get("symptoms", {})
    values = [info.get("chief_complaint", ""), *info.get("associated_symptoms", [])]
    if isinstance(nested, dict):
        values.extend(nested.get("summary", []))
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def patient_observation(case, state=None):
    source = case.get("patient_visible_info", {})
    allowed = ("chief_complaint", "history", "associated_symptoms", "secondary_symptoms",
               "past_medical_history", "medications", "allergies", "social_history",
               "review_of_systems", "age", "sex", "demographics", "symptoms", "current_medications")
    result = {key: deepcopy(source[key]) for key in allowed if key in source}
    if state is not None:
        get = state.get if isinstance(state, dict) else lambda k, d=None: getattr(state, k, d)
        result["current_symptoms"] = list(get("current_symptoms", []) or [])
    return result


def doctor_observation(runtime):
    visible = runtime.case_data.get("doctor_visible_info", {})
    return {"chief_complaint": visible.get("chief_complaint", ""),
            "demographics": visible.get("demographics", ""),
            "arrival_info": visible.get("arrival_info", ""),
            "vital_signs": deepcopy(runtime.vital_signs),
            "elapsed_minutes": max(0, runtime.current_time_min - runtime.arrival_time_min),
            "health_state": runtime.health_state,
            "current_symptoms": list(runtime.current_symptoms),
            "reassessment_pending": runtime.reassessment_pending,
            "reassessment_reason": runtime.reassessment_reason,
            "pending_results": deepcopy(runtime.pending_results),
            "history": deepcopy(runtime.question_history),
            "objective_findings": list(runtime.objective_findings),
            "consults": deepcopy(runtime.consult_history),
            "interventions": deepcopy(runtime.interventions),
            "longitudinal_memory": (deepcopy(runtime.memory_context)
                                    if runtime.memory_context.get("mode") != "none" else {}),
            "working_assessment": runtime.assessment_summary}
