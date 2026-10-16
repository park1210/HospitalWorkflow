from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


EventType = Literal[
    "case_started",
    "arrival_entered",
    "triage_queued",
    "triage_started",
    "triage_completed",
    "assessment_completed",
    "patient_moved",
    "question_asked",
    "answer_received",
    "test_ordered",
    "test_started",
    "test_resource_released",
    "test_completed",
    "result_received",
    "consult_requested",
    "specialist_dispatched",
    "specialist_arrived",
    "consult_started",
    "consult_note_added",
    "diagnosis_finalized",
    "observation_started",
    "discharge_started",
    "case_completed",
    "deterioration_triggered",
    "what_if_branch_started",
    "what_if_branch_completed",
]


@dataclass
class EventActor:
    id: str
    role: str
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EventTarget:
    id: str
    role: str
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ClinicalEvent:
    event_id: str
    run_id: str
    case_id: str
    minute: int
    tick: int
    phase: str
    actor: EventActor
    target: EventTarget
    event_type: EventType
    action: str
    location_id: str = ""
    resource_kind: str = ""
    rationale: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    state_delta: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "case_id": self.case_id,
            "minute": int(self.minute),
            "tick": int(self.tick),
            "phase": str(self.phase).strip(),
            "actor": self.actor.to_dict(),
            "target": self.target.to_dict(),
            "event_type": str(self.event_type).strip(),
            "action": str(self.action).strip(),
            "location_id": str(self.location_id).strip(),
            "resource_kind": str(self.resource_kind).strip(),
            "rationale": str(self.rationale).strip(),
            "payload": dict(self.payload or {}),
            "state_delta": dict(self.state_delta or {}),
            "meta": dict(self.meta or {}),
        }


def build_event_id(case_id: str, minute: int, event_type: str, ordinal: int = 0) -> str:
    normalized_case = str(case_id).strip() or "case"
    normalized_event = str(event_type).strip() or "event"
    return f"{normalized_case}_m{int(minute):04d}_{normalized_event}_{int(ordinal):02d}"


def make_clinical_event(
    *,
    run_id: str,
    case_id: str,
    minute: int,
    tick: int,
    phase: str,
    actor_id: str,
    actor_role: str,
    target_id: str,
    target_role: str,
    event_type: EventType,
    action: str,
    location_id: str = "",
    resource_kind: str = "",
    rationale: str = "",
    payload: dict[str, Any] | None = None,
    state_delta: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    ordinal: int = 0,
) -> ClinicalEvent:
    return ClinicalEvent(
        event_id=build_event_id(case_id, minute, event_type, ordinal),
        run_id=str(run_id).strip(),
        case_id=str(case_id).strip(),
        minute=int(minute or 0),
        tick=int(tick or minute or 0),
        phase=str(phase).strip(),
        actor=EventActor(id=str(actor_id).strip(), role=str(actor_role).strip()),
        target=EventTarget(id=str(target_id).strip(), role=str(target_role).strip()),
        event_type=event_type,
        action=str(action).strip(),
        location_id=str(location_id).strip(),
        resource_kind=str(resource_kind).strip(),
        rationale=str(rationale).strip(),
        payload=dict(payload or {}),
        state_delta=dict(state_delta or {}),
        meta=dict(meta or {}),
    )
