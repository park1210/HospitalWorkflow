from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


CaseWorkflowState = str


@dataclass
class HospitalCaseRuntime:
    case_id: str
    case_data: dict[str, Any]
    arrival_time_min: int
    arrival_index: int
    triage_level: int = 3
    triage_rationale: str = ""
    deterioration_risk: str = "low"
    zone: str = "not_arrived"
    workflow_state: CaseWorkflowState = "not_arrived"
    effective_priority: int = 3
    assigned_bed_id: str = ""
    assigned_er_doctor_id: str = ""
    assigned_specialist_id: str = ""
    assigned_consult_room_id: str = ""
    bed_assigned_min: int = 0
    er_arrival_min: int = 0
    er_started_min: int = 0
    specialty_arrival_min: int = 0
    specialty_started_min: int = 0
    current_location_id: str = ""
    target_location_id: str = ""
    interaction_location_id: str = ""
    movement_path: list[str] = field(default_factory=list)
    pending_interaction: dict[str, Any] = field(default_factory=dict)
    target_department: str = ""
    assessment_summary: str = ""
    recommended_tests: list[str] = field(default_factory=list)
    completed_tests: list[str] = field(default_factory=list)
    pending_results: list[dict[str, Any]] = field(default_factory=list)
    test_results: list[dict[str, Any]] = field(default_factory=list)
    objective_findings: list[str] = field(default_factory=list)
    question_history: list[dict[str, str]] = field(default_factory=list)
    consult_history: list[dict[str, str]] = field(default_factory=list)
    decision_snapshots: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    latest_rationale: str = ""
    latest_action: str = ""
    latest_actor: str = ""
    latest_target: str = ""
    er_turn_count: int = 0
    specialty_turn_count: int = 0
    is_completed: bool = False

    def waiting_minutes(self, current_minute: int) -> int:
        return max(0, int(current_minute or 0) - int(self.arrival_time_min or 0))

    @classmethod
    def from_summary(cls, summary: dict[str, Any], case_data: dict[str, Any] | None = None) -> "HospitalCaseRuntime":
        payload = dict(summary or {})
        return cls(
            case_id=str(payload.get("case_id", "")).strip(),
            case_data=dict(case_data or {}),
            arrival_time_min=int(payload.get("arrival_time_min", 0) or 0),
            arrival_index=int(payload.get("arrival_index", 0) or 0),
            triage_level=int(payload.get("triage_level", 3) or 3),
            triage_rationale=str(payload.get("triage_rationale", "")).strip(),
            deterioration_risk=str(payload.get("deterioration_risk", "")).strip() or "low",
            zone=str(payload.get("zone", "")).strip() or "not_arrived",
            workflow_state=str(payload.get("workflow_state", "")).strip() or "not_arrived",
            effective_priority=int(payload.get("effective_priority", payload.get("triage_level", 3)) or 3),
            assigned_bed_id=str(payload.get("assigned_bed_id", "")).strip(),
            assigned_er_doctor_id=str(payload.get("assigned_er_doctor_id", "")).strip(),
            assigned_specialist_id=str(payload.get("assigned_specialist_id", "")).strip(),
            assigned_consult_room_id=str(payload.get("assigned_consult_room_id", "")).strip(),
            bed_assigned_min=int(payload.get("bed_assigned_min", 0) or 0),
            er_arrival_min=int(payload.get("er_arrival_min", 0) or 0),
            er_started_min=int(payload.get("er_started_min", 0) or 0),
            specialty_arrival_min=int(payload.get("specialty_arrival_min", 0) or 0),
            specialty_started_min=int(payload.get("specialty_started_min", 0) or 0),
            current_location_id=str(payload.get("current_location_id", "")).strip(),
            target_location_id=str(payload.get("target_location_id", "")).strip(),
            interaction_location_id=str(payload.get("interaction_location_id", "")).strip(),
            movement_path=[str(item).strip() for item in list(payload.get("movement_path", []) or []) if str(item).strip()],
            pending_interaction=dict(payload.get("pending_interaction", {}) or {}),
            target_department=str(payload.get("target_department", "")).strip(),
            assessment_summary=str(payload.get("assessment_summary", "")).strip(),
            recommended_tests=[str(item).strip() for item in list(payload.get("recommended_tests", []) or []) if str(item).strip()],
            completed_tests=[str(item).strip() for item in list(payload.get("completed_tests", []) or []) if str(item).strip()],
            pending_results=[dict(item or {}) for item in list(payload.get("pending_results", []) or [])],
            test_results=[dict(item or {}) for item in list(payload.get("test_results", []) or [])],
            objective_findings=[str(item).strip() for item in list(payload.get("objective_findings", []) or []) if str(item).strip()],
            question_history=[dict(item or {}) for item in list(payload.get("question_history", []) or [])],
            consult_history=[dict(item or {}) for item in list(payload.get("consult_history", []) or [])],
            decision_snapshots=[dict(item or {}) for item in list(payload.get("decision_snapshots", []) or [])],
            alerts=[str(item).strip() for item in list(payload.get("alerts", []) or []) if str(item).strip()],
            latest_rationale=str(payload.get("latest_rationale", "")).strip(),
            latest_action=str(payload.get("latest_action", "")).strip(),
            latest_actor=str(payload.get("latest_actor", "")).strip(),
            latest_target=str(payload.get("latest_target", "")).strip(),
            er_turn_count=int(payload.get("er_turn_count", 0) or 0),
            specialty_turn_count=int(payload.get("specialty_turn_count", 0) or 0),
            is_completed=bool(payload.get("is_completed", False)),
        )

    def to_summary(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "arrival_time_min": int(self.arrival_time_min or 0),
            "arrival_index": int(self.arrival_index or 0),
            "triage_level": int(self.triage_level or 3),
            "effective_priority": int(self.effective_priority or self.triage_level or 3),
            "triage_rationale": str(self.triage_rationale).strip(),
            "deterioration_risk": str(self.deterioration_risk).strip(),
            "zone": str(self.zone).strip(),
            "workflow_state": str(self.workflow_state).strip(),
            "assigned_bed_id": str(self.assigned_bed_id).strip(),
            "assigned_er_doctor_id": str(self.assigned_er_doctor_id).strip(),
            "assigned_specialist_id": str(self.assigned_specialist_id).strip(),
            "assigned_consult_room_id": str(self.assigned_consult_room_id).strip(),
            "bed_assigned_min": int(self.bed_assigned_min or 0),
            "er_arrival_min": int(self.er_arrival_min or 0),
            "er_started_min": int(self.er_started_min or 0),
            "specialty_arrival_min": int(self.specialty_arrival_min or 0),
            "specialty_started_min": int(self.specialty_started_min or 0),
            "current_location_id": str(self.current_location_id).strip(),
            "target_location_id": str(self.target_location_id).strip(),
            "interaction_location_id": str(self.interaction_location_id).strip(),
            "movement_path": [str(item).strip() for item in list(self.movement_path or []) if str(item).strip()],
            "pending_interaction": dict(self.pending_interaction or {}),
            "target_department": str(self.target_department).strip(),
            "assessment_summary": str(self.assessment_summary).strip(),
            "recommended_tests": list(self.recommended_tests),
            "completed_tests": list(self.completed_tests),
            "pending_results": [dict(item or {}) for item in list(self.pending_results)],
            "test_results": [dict(item or {}) for item in list(self.test_results)],
            "pending_results_count": len(self.pending_results),
            "objective_findings": list(self.objective_findings),
            "question_history": [dict(item or {}) for item in list(self.question_history)],
            "question_count": len(self.question_history),
            "consult_history": [dict(item or {}) for item in list(self.consult_history)],
            "consult_count": len(self.consult_history),
            "decision_snapshots": [dict(item or {}) for item in list(self.decision_snapshots)],
            "alerts": list(self.alerts),
            "latest_rationale": str(self.latest_rationale).strip(),
            "latest_action": str(self.latest_action).strip(),
            "latest_actor": str(self.latest_actor).strip(),
            "latest_target": str(self.latest_target).strip(),
            "er_turn_count": int(self.er_turn_count or 0),
            "specialty_turn_count": int(self.specialty_turn_count or 0),
            "is_completed": bool(self.is_completed),
        }
