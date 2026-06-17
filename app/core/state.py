from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.core.event_schema import ClinicalEvent


@dataclass
class ReasoningState:
    case_id: str
    current_time_min: int = 0
    arrival_time_min: int = 0
    last_seen_time_min: int = 0
    next_reassessment_time_min: int | None = None
    observation_status: str = ""
    deterioration_risk: str = ""
    triage_level: int = 3
    triage_rationale: str = ""
    is_immediately_unstable: bool = False
    needs_resuscitation_now: bool = False
    arrival_info: str = ""
    vital_signs: dict[str, Any] = field(default_factory=dict)
    working_problem_list: list[str] = field(default_factory=list)
    red_flags: list[str] = field(default_factory=list)
    stabilization_actions: list[str] = field(default_factory=list)
    stabilized_after_intervention: bool = True
    known_information: list[str] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)
    suspected_diagnoses: list[str] = field(default_factory=list)
    candidate_scores: dict[str, float] = field(default_factory=dict)
    family_signal_scores: dict[str, float] = field(default_factory=dict)
    suspected_system: str = ""
    department_routing_scores: dict[str, float] = field(default_factory=dict)
    department_routing_candidates: list[str] = field(default_factory=list)
    er_routing_analysis: dict[str, Any] = field(default_factory=dict)
    diagnostic_handoff_analysis: dict[str, Any] = field(default_factory=dict)
    next_action: str = "ask"
    recommended_tests: list[str] = field(default_factory=list)
    requested_tests: list[str] = field(default_factory=list)
    requested_exams: list[str] = field(default_factory=list)
    requested_consults: list[str] = field(default_factory=list)
    consultation_history: list[dict[str, str]] = field(default_factory=list)
    decision_history: list[dict[str, str]] = field(default_factory=list)
    summary: str = ""
    er_assessment: str = ""
    objective_findings: list[str] = field(default_factory=list)
    consult_recommendations: list[dict[str, Any]] = field(default_factory=list)
    er_working_diagnosis: str = ""
    responsible_department: str = ""
    diagnostic_service: str = ""
    diagnostic_handoff_rationale: str = ""
    diagnostic_handoff_confidence: float = 0.0
    ipass_handoff: dict[str, Any] = field(default_factory=dict)
    er_final_diagnosis: str = ""
    er_final_department: str = ""
    er_confidence: float = 0.0
    reasoning_plan_generated: bool = False
    latest_rationale: str = ""
    final_diagnosis: str = ""
    final_department: str = ""
    final_decision_source: str = ""
    chief_doctor_called: bool = False
    reflection_count: int = 0
    reflection_triggers: list[str] = field(default_factory=list)
    llm_self_reflection_count: int = 0
    llm_call_count: int = 0
    specialty_llm_attempt_count: int = 0
    specialty_llm_success_count: int = 0
    specialty_llm_failures: list[str] = field(default_factory=list)
    specialty_llm_debug: list[dict[str, Any]] = field(default_factory=list)
    resource_status: dict[str, Any] = field(default_factory=dict)
    resource_events: list[dict[str, Any]] = field(default_factory=list)
    pending_results: list[dict[str, Any]] = field(default_factory=list)
    time_events: list[dict[str, Any]] = field(default_factory=list)
    deterioration_events: list[dict[str, Any]] = field(default_factory=list)
    applied_temporal_event_keys: list[str] = field(default_factory=list)
    what_if_shadow_events: list[dict[str, Any]] = field(default_factory=list)
    what_if_applied_events: list[dict[str, Any]] = field(default_factory=list)
    what_if_stats: dict[str, Any] = field(default_factory=dict)
    counterfactual_action_candidates: list[dict[str, Any]] = field(default_factory=list)
    decision_snapshots: list[dict[str, Any]] = field(default_factory=list)
    what_if_replay_history: list[dict[str, Any]] = field(default_factory=list)
    event_log: list[dict[str, Any]] = field(default_factory=list)
    turn_count: int = 0
    trajectory_steps: list[dict[str, Any]] = field(default_factory=list)
    episode_reward: float = 0.0
    reward_breakdown: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def initialize_reasoning_state(case: dict[str, Any]) -> ReasoningState:
    doctor_visible = case.get("doctor_visible_info", {})
    temporal_profile = case.get("temporal_profile", {}) if isinstance(case.get("temporal_profile", {}), dict) else {}
    deterioration_model = (
        temporal_profile.get("deterioration_model", {})
        if isinstance(temporal_profile.get("deterioration_model", {}), dict)
        else {}
    )
    chief_complaint = str(doctor_visible.get("chief_complaint", "")).strip()
    demographics = str(doctor_visible.get("demographics", "")).strip()
    arrival_info = str(doctor_visible.get("arrival_info", "")).strip()
    initial_vitals = doctor_visible.get("initial_vitals", {}) if isinstance(doctor_visible.get("initial_vitals", {}), dict) else {}
    arrival_time_min = int(
        temporal_profile.get("arrival_time_min", case.get("arrival_time_min", 0)) or 0
    )

    known_information = [item for item in [demographics, chief_complaint, arrival_info] if item]
    missing_information = [
        "symptom onset and duration",
        "associated symptoms",
        "aggravating or relieving factors",
    ]

    return ReasoningState(
        case_id=str(case.get("case_id", "")),
        current_time_min=arrival_time_min,
        arrival_time_min=arrival_time_min,
        last_seen_time_min=arrival_time_min,
        deterioration_risk=str(deterioration_model.get("baseline_risk", "")).strip(),
        arrival_info=arrival_info,
        vital_signs=initial_vitals,
        known_information=known_information,
        missing_information=missing_information,
        summary=str(doctor_visible.get("initial_summary", "")).strip(),
    )


def append_known_information(state: ReasoningState, text: str) -> None:
    value = str(text).strip()
    if value and value not in state.known_information:
        state.known_information.append(value)


def record_exam_request(state: ReasoningState, exam_name: str) -> None:
    normalized = str(exam_name).strip()
    if normalized and normalized not in state.requested_exams:
        state.requested_exams.append(normalized)


def record_test_request(state: ReasoningState, test_name: str) -> None:
    normalized = str(test_name).strip()
    if normalized and normalized not in state.requested_tests:
        state.requested_tests.append(normalized)


def record_consultation(state: ReasoningState, department: str, opinion: str) -> None:
    normalized_department = str(department).strip()
    normalized_opinion = str(opinion).strip()
    if normalized_department:
        if normalized_department not in state.requested_consults:
            state.requested_consults.append(normalized_department)
        state.consultation_history.append(
            {
                "department": normalized_department,
                "opinion": normalized_opinion,
            }
        )
        state.consult_recommendations.append(
            {
                "department": normalized_department,
                "recommendation": normalized_opinion,
            }
        )


def record_decision(state: ReasoningState, actor: str, action: str, rationale: str) -> None:
    state.latest_rationale = str(rationale).strip()
    state.decision_history.append(
        {
            "actor": str(actor).strip(),
            "action": str(action).strip(),
            "rationale": str(rationale).strip(),
        }
    )


def record_trajectory_step(state: ReasoningState, step: dict[str, Any]) -> None:
    state.trajectory_steps.append(step)


def record_time_event(state: ReasoningState, event: dict[str, Any]) -> None:
    state.time_events.append(event)


def record_deterioration_event(state: ReasoningState, event: dict[str, Any]) -> None:
    state.deterioration_events.append(event)


def record_resource_event(state: ReasoningState, event: dict[str, Any]) -> None:
    state.resource_events.append(event)


def record_what_if_event(state: ReasoningState, event: dict[str, Any]) -> None:
    state.what_if_shadow_events.append(event)
    state.what_if_stats["shadow_event_count"] = len(state.what_if_shadow_events)

    def _action_signature(action: dict[str, Any]) -> tuple[str, str]:
        return (
            str((action or {}).get("type", "")).strip(),
            str((action or {}).get("target", "")).strip(),
        )

    disagreement_count = sum(
        1
        for item in state.what_if_shadow_events
        if item.get("selected_action")
        and _action_signature(item.get("proposed_action", {}) or {})
        != _action_signature(item.get("selected_action", {}) or {})
    )
    state.what_if_stats["shadow_disagreement_count"] = disagreement_count


def record_what_if_applied(state: ReasoningState, event: dict[str, Any]) -> None:
    state.what_if_applied_events.append(event)
    state.what_if_stats["applied_event_count"] = len(state.what_if_applied_events)


def record_decision_snapshot(state: ReasoningState, snapshot: dict[str, Any]) -> None:
    state.decision_snapshots.append(snapshot)
    state.what_if_stats["decision_snapshot_count"] = len(state.decision_snapshots)


def record_what_if_replay(state: ReasoningState, replay_result: dict[str, Any]) -> None:
    state.what_if_replay_history.append(replay_result)
    state.what_if_stats["replay_count"] = len(state.what_if_replay_history)


def record_clinical_event(state: ReasoningState, event: ClinicalEvent | dict[str, Any]) -> None:
    serialized = event.to_dict() if isinstance(event, ClinicalEvent) else dict(event or {})
    if not serialized:
        return
    state_delta = dict(serialized.get("state_delta", {}) or {})
    actor = serialized.get("actor", {})
    target = serialized.get("target", {})
    serialized["run_id"] = str(serialized.get("run_id", "")).strip()
    serialized["payload"] = dict(serialized.get("payload", {}) or {})
    serialized["state_delta"] = state_delta
    serialized["meta"] = dict(serialized.get("meta", {}) or {})
    serialized["actor"] = dict(actor or {}) if isinstance(actor, dict) else {"id": str(actor).strip(), "role": ""}
    serialized["target"] = dict(target or {}) if isinstance(target, dict) else {"id": str(target).strip(), "role": ""}
    if not str(serialized.get("zone", "")).strip():
        serialized["zone"] = str(state_delta.get("zone", "")).strip()
    state.event_log.append(serialized)
