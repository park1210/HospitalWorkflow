from typing import Any


VALID_ACTIONS = {"ask", "test", "consult", "diagnose", "disposition"}


def _normalize_question(text: str) -> str:
    return " ".join(str(text).strip().lower().split())


def route_next_action(reasoning_output: dict[str, Any], state: dict[str, Any], case: dict[str, Any]) -> dict[str, str]:
    requested_tests = set(state.get("requested_tests", []))
    requested_consults = set(state.get("requested_consults", []))
    available_tests = case.get("meta", {}).get("available_test_sections", []) or []
    transcript = case.get("_working_transcript", [])

    next_action = str(reasoning_output.get("next_action", "ask")).strip().lower()
    if next_action not in VALID_ACTIONS:
        next_action = "ask"

    asked_questions = [
        _normalize_question(entry.get("content", ""))
        for entry in transcript
        if entry.get("role") == "er_interview_doctor"
    ]
    patient_answers = [
        _normalize_question(entry.get("content", ""))
        for entry in transcript
        if entry.get("role") == "patient"
    ]
    recommended_tests = [str(item).strip() for item in reasoning_output.get("recommended_tests", []) if str(item).strip()]

    if next_action == "ask" and len(patient_answers) >= 2 and recommended_tests:
        next_action = "test"

    if next_action == "ask" and len(asked_questions) >= 2:
        if asked_questions[-1] and asked_questions[-1] == asked_questions[-2] and recommended_tests:
            next_action = "test"
        elif len(asked_questions) >= 3 and len(set(asked_questions[-3:])) == 1:
            if recommended_tests:
                next_action = "test"
            elif str(reasoning_output.get("target_department", "")).strip():
                next_action = "consult"

    if next_action == "ask" and state.get("requested_tests") and str(reasoning_output.get("target_department", "")).strip():
        next_action = "consult"

    if next_action == "test":
        for test_name in recommended_tests:
            if test_name not in requested_tests:
                return {"action": "test", "target": test_name, "stage": "er"}
        for test_name in available_tests:
            if test_name not in requested_tests:
                return {"action": "test", "target": test_name, "stage": "er"}
        next_action = "consult"

    if next_action == "consult":
        target_department = str(reasoning_output.get("target_department", "")).strip().lower()
        if target_department and target_department not in requested_consults:
            return {"action": "consult", "target": target_department, "stage": "specialty"}
        next_action = "diagnose"

    if next_action in {"diagnose", "disposition"}:
        return {"action": "diagnose", "target": "", "stage": "er_disposition"}

    return {"action": "ask", "target": "", "stage": "er"}
