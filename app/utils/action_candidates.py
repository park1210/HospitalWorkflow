from __future__ import annotations

from typing import Any

from app.config import settings

GENERIC_DIAGNOSIS_PREFIXES = (
    "possible ",
    "undifferentiated",
    "acute abdominal",
    "acute ",
)


def _is_specific_diagnosis_text(diagnosis: str) -> bool:
    normalized = str(diagnosis).strip().lower()
    if not normalized:
        return False
    return not any(normalized.startswith(prefix) for prefix in GENERIC_DIAGNOSIS_PREFIXES)


def build_er_next_step_candidates(
    state_dict: dict[str, Any],
    proposed_action: str,
    proposed_target: str,
) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []

    def _append(action: str, target: str = "") -> None:
        spec = {"type": action, "target": str(target).strip()}
        if spec not in candidates:
            candidates.append(spec)

    _append(proposed_action, proposed_target)

    requested_tests = {str(item).strip() for item in state_dict.get("requested_tests", []) if str(item).strip()}
    recommended_tests = [str(item).strip() for item in state_dict.get("recommended_tests", []) if str(item).strip()]
    remaining_tests = [item for item in recommended_tests if item not in requested_tests]

    if not state_dict.get("objective_findings"):
        _append("ask_patient", "")
    if remaining_tests:
        _append("request_test", remaining_tests[0])
    _append("make_diagnostic_summary", "")

    return candidates[: max(2, settings.WHAT_IF_MAX_ALTERNATIVES)]


def build_specialty_finalize_candidates(
    state_dict: dict[str, Any],
    *,
    proposed_action: str,
    proposed_target: str,
    refined_diagnosis: str,
    next_test: str,
    llm_candidate_diagnoses: list[str] | None = None,
) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []

    def _append(action: str, target: str = "") -> None:
        spec = {"type": str(action).strip(), "target": str(target).strip()}
        if spec not in candidates:
            candidates.append(spec)

    _append(proposed_action, proposed_target)
    _append("diagnose_now", "")

    if str(next_test).strip():
        _append("request_test", next_test)

    candidate_pool = [str(item).strip() for item in list(llm_candidate_diagnoses or []) if str(item).strip()]
    objective_count = len(list(state_dict.get("objective_findings", []) or []))
    if (
        not _is_specific_diagnosis_text(refined_diagnosis)
        or len(candidate_pool) > 1
        or (objective_count >= 2 and not str(next_test).strip())
    ):
        _append("refine_again", "")

    return candidates[: max(2, settings.WHAT_IF_MAX_ALTERNATIVES)]


def build_specialty_next_step_candidates(
    *,
    proposed_action: str,
    proposed_target: str,
    can_ask_patient: bool,
    next_test: str,
) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []

    def _append(action: str, target: str = "") -> None:
        spec = {"type": str(action).strip(), "target": str(target).strip()}
        if spec not in candidates:
            candidates.append(spec)

    _append(proposed_action, proposed_target)
    if can_ask_patient:
        _append("ask_patient", "")
    if str(next_test).strip():
        _append("request_test", next_test)
    _append("diagnose_now", "")

    return candidates[: max(2, settings.WHAT_IF_MAX_ALTERNATIVES)]


def build_er_routing_candidates(
    state_dict: dict[str, Any],
    routing_analysis: dict[str, Any],
) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []

    def _append(action_type: str, target: str = "") -> None:
        spec = {"type": action_type, "target": str(target).strip()}
        if spec not in candidates:
            candidates.append(spec)

    chosen = str(routing_analysis.get("chosen_department", "")).strip()
    if chosen:
        _append("handoff_department", chosen)

    routing_departments = [str(department).strip() for department in list(routing_analysis.get("routing_candidates", []) or [])[:2] if str(department).strip()]
    for department in routing_departments:
        normalized = str(department).strip()
        if normalized:
            _append("handoff_department", normalized)

    alternative_department = ""
    for department in routing_departments:
        if department and department != chosen:
            alternative_department = department
            break
    if alternative_department:
        _append("consult_before_handoff", alternative_department)

    requested_tests = {str(item).strip() for item in state_dict.get("requested_tests", []) if str(item).strip()}
    recommended_tests = [str(item).strip() for item in state_dict.get("recommended_tests", []) if str(item).strip()]
    remaining_tests = [item for item in recommended_tests if item not in requested_tests]
    if remaining_tests:
        _append("request_test_before_handoff", remaining_tests[0])

    return candidates[: max(2, settings.WHAT_IF_MAX_ALTERNATIVES)]
