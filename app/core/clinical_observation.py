"""Explicit role projections: never send the complete case to a model."""
from copy import deepcopy


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
