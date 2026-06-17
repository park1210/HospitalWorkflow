from __future__ import annotations

from typing import Any

from app.config import settings
from app.core.evaluator import evaluate_department, evaluate_diagnosis


def build_step_reward_breakdown(
    action: str,
    *,
    state_snapshot: dict[str, Any] | None = None,
    target: str = "",
    used_reasoning_llm: bool = False,
    used_reflection_llm: bool = False,
) -> dict[str, float]:
    state_snapshot = state_snapshot or {}
    target_department = str(target).strip().lower()
    unstable = bool(state_snapshot.get("is_immediately_unstable")) or bool(state_snapshot.get("needs_resuscitation_now"))
    has_objective_evidence = bool(state_snapshot.get("has_objective_evidence"))
    requested_consults_count = int(state_snapshot.get("requested_consults_count", 0) or 0)

    breakdown = {
        "turn_penalty": -settings.REWARD_TURN_PENALTY,
        "llm_call_penalty": 0.0,
        "ask_delay_penalty": 0.0,
        "test_penalty": 0.0,
        "consult_penalty": 0.0,
        "appropriate_test_bonus": 0.0,
        "appropriate_consult_bonus": 0.0,
    }

    if used_reasoning_llm:
        breakdown["llm_call_penalty"] -= settings.REWARD_LLM_CALL_PENALTY
    if used_reflection_llm:
        breakdown["llm_call_penalty"] -= settings.REWARD_LLM_CALL_PENALTY
    if action in {"ask", "ask_patient"} and (unstable or has_objective_evidence):
        breakdown["ask_delay_penalty"] -= settings.REWARD_ASK_DELAY_PENALTY
    if action in {"test", "request_test"}:
        breakdown["test_penalty"] -= settings.REWARD_TEST_PENALTY
        if unstable or not has_objective_evidence:
            breakdown["appropriate_test_bonus"] += settings.REWARD_APPROPRIATE_TEST_BONUS
    if action in {"consult", "consult_specialty", "consult_before_handoff"}:
        breakdown["consult_penalty"] -= settings.REWARD_CONSULT_PENALTY
        if has_objective_evidence and target_department and target_department not in {"general_medicine", "radiology"}:
            breakdown["appropriate_consult_bonus"] += settings.REWARD_APPROPRIATE_CONSULT_BONUS
        if requested_consults_count > 0:
            breakdown["consult_penalty"] -= settings.REWARD_CONSULT_PENALTY * 0.5
    return breakdown


def score_step_reward(breakdown: dict[str, float]) -> float:
    return float(sum(breakdown.values()))


def build_episode_reward_breakdown(
    case: dict[str, Any],
    state: dict[str, Any],
    final_diagnosis: str,
    final_department: str,
) -> dict[str, float]:
    gold = case.get("gold_label", {})
    diagnosis_correct = evaluate_diagnosis(final_diagnosis, str(gold.get("diagnosis", "")))
    department_correct = evaluate_department(final_department, str(gold.get("department", "")))
    department_evaluable = department_correct is not None

    decision_history = state.get("decision_history", []) or []
    rationale_count = sum(1 for item in decision_history if str(item.get("rationale", "")).strip())
    rationale_ratio = (rationale_count / len(decision_history)) if decision_history else 0.0
    responsible_department = str(state.get("responsible_department", "")).strip()
    working_diagnosis = str(state.get("er_working_diagnosis", "")).strip()
    diagnostic_service = str(state.get("diagnostic_service", "")).strip()
    handoff_complete = bool(working_diagnosis and responsible_department and diagnostic_service)

    breakdown = {
        "diagnosis_outcome": (
            settings.REWARD_DIAGNOSIS_CORRECT if diagnosis_correct else settings.REWARD_DIAGNOSIS_INCORRECT
        ),
        "department_outcome": (
            (
                settings.REWARD_DEPARTMENT_CORRECT
                if department_correct is True
                else settings.REWARD_DEPARTMENT_INCORRECT
            )
            if department_evaluable
            else 0.0
        ),
        "er_decisive_bonus": 0.0,
        "diagnostic_handoff_bonus": settings.REWARD_DIAGNOSTIC_HANDOFF_COMPLETENESS if handoff_complete else 0.0,
        "chief_doctor_penalty": 0.0,
        "rationale_bonus": settings.REWARD_RATIONALE_RECORDED * rationale_ratio,
    }

    if str(state.get("final_decision_source", "")).strip().startswith("er") and diagnosis_correct:
        breakdown["er_decisive_bonus"] += settings.REWARD_ER_DECISIVE_BONUS
    if bool(state.get("chief_doctor_called")):
        breakdown["chief_doctor_penalty"] -= settings.REWARD_CHIEF_DOCTOR_PENALTY
    return breakdown


def finalize_trajectory(
    steps: list[dict[str, Any]],
    episode_breakdown: dict[str, float],
) -> tuple[list[dict[str, Any]], float]:
    terminal_reward = float(sum(episode_breakdown.values()))
    running_return = terminal_reward
    annotated_steps = [dict(step) for step in steps]

    for index in range(len(annotated_steps) - 1, -1, -1):
        step = annotated_steps[index]
        immediate_reward = float(step.get("immediate_reward", 0.0) or 0.0)
        running_return += immediate_reward
        step["return_to_go"] = round(running_return, 4)
        if index == len(annotated_steps) - 1:
            step["terminal_reward"] = round(terminal_reward, 4)

    return annotated_steps, running_return
