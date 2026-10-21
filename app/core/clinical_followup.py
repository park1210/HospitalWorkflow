"""Low-cost change detection; no diagnostic or physiological thresholds."""
import hashlib
import json


def review_signature(runtime):
    # Deliberately excludes the clock and consult opinions:
    # neither alone justifies calling the same department again.
    payload = {
        "findings": runtime.objective_findings,
        "vitals": runtime.vital_signs,
        "symptoms": runtime.current_symptoms,
        "health": runtime.health_state,
    }

    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
        ).encode()
    ).hexdigest()


def available_consult_departments(
    runtime,
    departments,
    current="",
):
    signature = review_signature(runtime)

    latest = {
        item["department"]: item.get("review_signature")
        for item in runtime.consult_history
    }

    return [
        department
        for department in departments
        if department != current
        and (
            department not in latest
            or (
                latest[department] is not None
                and latest[department] != signature
            )
        )
    ]