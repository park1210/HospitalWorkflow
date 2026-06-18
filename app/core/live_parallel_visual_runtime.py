from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from app.config import settings
from app.core.hospital_scene_builder import build_hospital_scene_snapshot
from app.core.hospital_scheduler_state import HospitalSchedulerState
from app.core.logger import get_run_dir


ZONE_ORDER = [
    "waiting_room",
    "er_workup",
    "observation",
    "awaiting_results",
    "specialty_review",
    "completed",
]


def _bed_suffix(location_id: str) -> str:
    value = str(location_id).strip()
    if value.startswith("er_bed_"):
        return value.split("er_bed_", 1)[-1]
    return ""


def _assigned_nurse_id(runtime: Any) -> str:
    suffix = _bed_suffix(str(getattr(runtime, "assigned_bed_id", "")).strip())
    return f"nurse_bed_{suffix}" if suffix else "nurse_bed_1"


def _bedside_location_for_runtime(runtime: Any) -> str:
    suffix = _bed_suffix(str(getattr(runtime, "assigned_bed_id", "")).strip())
    return f"er_bedside_{suffix}" if suffix else (str(getattr(runtime, "assigned_bed_id", "")).strip() or "er_bed_1")


def _nurse_base_location_for_runtime(runtime: Any) -> str:
    suffix = _bed_suffix(str(getattr(runtime, "assigned_bed_id", "")).strip())
    return f"nurse_base_{suffix}" if suffix else "nurse_base_1"


def _visible_diagnosis(runtime: Any) -> str:
    action = str(getattr(runtime, "latest_action", "")).strip()
    workflow = str(getattr(runtime, "workflow_state", "")).strip()
    if action in {"er_finalize", "specialty_finalize"} or workflow == "completed" or bool(getattr(runtime, "is_completed", False)):
        return str(getattr(runtime, "assessment_summary", "")).strip()
    return ""


def _dialogue_interaction_location(runtime: Any, action: str) -> str:
    normalized = str(action).strip()
    if normalized in {"ask_history", "order_test", "test_result_ready", "er_finalize", "specialty_consult", "consult_started", "specialty_finalize"}:
        return _bedside_location_for_runtime(runtime)
    return ""


def _dialogue_ready_for_runtime(runtime: Any, action: str, current_minute: int) -> bool:
    normalized = str(action).strip()
    minute = int(current_minute or 0)
    if normalized == "request_specialty":
        return True
    if normalized in {"ask_history", "order_test", "test_result_ready", "er_finalize"}:
        started_min = int(getattr(runtime, "er_started_min", 0) or 0)
        arrival_min = int(getattr(runtime, "er_arrival_min", 0) or 0)
        if started_min > 0:
            return minute >= started_min
        return arrival_min <= 0 or minute >= arrival_min
    if normalized in {"specialty_consult", "consult_started", "specialty_finalize"}:
        started_min = int(getattr(runtime, "specialty_started_min", 0) or 0)
        arrival_min = int(getattr(runtime, "specialty_arrival_min", 0) or 0)
        if started_min > 0:
            return minute >= started_min
        return arrival_min <= 0 or minute >= arrival_min
    return True


class LiveParallelVisualRuntimeWriter:
    def __init__(
        self,
        run_id: str,
        queue_policy: str,
        step_delay_sec: Optional[float] = None,
        demo_context: Optional[dict[str, Any]] = None,
    ) -> None:
        self.run_id = run_id
        self.queue_policy = queue_policy
        self.demo_context = dict(demo_context or {})
        delay_from_env = float(os.getenv("LIVE_VIS_STEP_DELAY_SEC", "0.55") or 0.55)
        self.step_delay_sec = delay_from_env if step_delay_sec is None else max(0.0, float(step_delay_sec))
        self.report_dir = get_run_dir(settings.REPORTS_DIR, run_id)
        self.snapshot_path = self.report_dir / "live_visual_state.json"
        self.history_path = self.report_dir / "live_visual_history.json"
        self.history: list[dict[str, Any]] = []
        self.conversation_history: list[dict[str, Any]] = []
        self._recent_signatures: list[tuple[str, str, tuple[str, ...]]] = []
        self._last_dialogue_event_id: str = ""

    @staticmethod
    def _patient_summary_line(runtime: Any) -> str:
        question_history = list(getattr(runtime, "question_history", []) or [])
        if question_history:
            latest = dict(question_history[-1] or {})
            answer = str(latest.get("answer", "")).strip()
            if answer:
                return answer
        objective_findings = [str(item).strip() for item in list(getattr(runtime, "objective_findings", []) or []) if str(item).strip()]
        if objective_findings:
            return objective_findings[-1]
        return "The symptoms are still present."

    def initialize(self, state: HospitalSchedulerState) -> None:
        self._write_snapshot(state, phase="initialized", actor="system", action="initialized")

    def on_step(self, state: HospitalSchedulerState) -> None:
        latest_event = dict(state.event_log[-1] if state.event_log else {})
        self._write_snapshot(
            state,
            phase=str(latest_event.get("action", "")).strip() or "tick",
            actor=self._event_actor_id(latest_event) or "system",
            action=str(latest_event.get("action", "")).strip() or "tick",
        )

    def finalize(self, state: HospitalSchedulerState) -> None:
        self._write_snapshot(state, phase="completed", actor="system", action="completed")

    @staticmethod
    def _atomic_write_json(path: Path, payload: Any) -> None:
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)

    def _scheduler_zone(self, runtime: Any) -> str:
        workflow = str(getattr(runtime, "workflow_state", "")).strip()
        zone = str(getattr(runtime, "zone", "")).strip()
        if workflow in {"completed"} or zone == "discharged":
            return "completed"
        if workflow in {"waiting_triage", "waiting_bed"}:
            return "waiting_room"
        if workflow in {"waiting_er_doctor_arrival"}:
            return "er_workup"
        if workflow in {"waiting_test", "awaiting_results", "result_ready_hold"}:
            return "awaiting_results"
        if workflow in {"waiting_specialty", "in_specialty_consult"}:
            return "er_workup"
        if workflow in {"waiting_er", "in_er_interview"}:
            return "er_workup"
        if zone in {"waiting_room", "er_workup", "observation", "awaiting_results", "specialty_review", "completed"}:
            return zone
        return "waiting_room"

    def _movement_target_id(self, runtime: Any, zone: str) -> str:
        explicit_target = str(getattr(runtime, "target_location_id", "")).strip()
        if explicit_target:
            return explicit_target
        workflow = str(getattr(runtime, "workflow_state", "")).strip()
        if workflow == "waiting_triage":
            return "arrival_lane_1"
        if workflow == "waiting_bed":
            return "triage_queue_1"
        if zone == "er_workup":
            return str(getattr(runtime, "assigned_bed_id", "")).strip() or "er_bed_1"
        if zone == "awaiting_results":
            pending_results = list(getattr(runtime, "pending_results", []) or [])
            if pending_results:
                resource_type = str(dict(pending_results[0]).get("resource_type", "")).strip()
                return "imaging_wait_1" if resource_type == "imaging_slot" else "lab_wait_1"
            return "lab_wait_1"
        if zone == "specialty_review":
            return str(getattr(runtime, "assigned_consult_room_id", "")).strip() or "specialty_consult_1"
        if zone == "completed":
            return "discharge_1"
        return "waiting_chair_1"

    def _patient_alerts(self, runtime: Any) -> list[str]:
        alerts = [str(item).strip() for item in list(getattr(runtime, "alerts", []) or []) if str(item).strip()]
        if list(getattr(runtime, "pending_results", []) or []):
            alerts.append("pending_result")
        if str(getattr(runtime, "deterioration_risk", "")).strip().lower() == "high":
            alerts.append("deterioration")
        deduped: list[str] = []
        for item in alerts:
            if item not in deduped:
                deduped.append(item)
        return deduped

    def _patients(self, state: HospitalSchedulerState) -> list[dict[str, Any]]:
        patients: list[dict[str, Any]] = []
        for case_id, runtime in state.cases.items():
            workflow = str(runtime.workflow_state).strip()
            if workflow == "not_arrived":
                continue
            zone = self._scheduler_zone(runtime)
            assigned_staff = ""
            if workflow in {"waiting_er", "waiting_er_doctor_arrival", "in_er_interview"}:
                assigned_staff = str(runtime.assigned_er_doctor_id).strip() or "doctor_er_0"
            elif workflow in {"waiting_triage", "waiting_bed", "waiting_test", "awaiting_results", "completed"}:
                assigned_staff = _assigned_nurse_id(runtime)
            elif workflow in {"waiting_specialty", "in_specialty_consult"}:
                assigned_staff = str(runtime.assigned_specialist_id).strip()
            patients.append(
                {
                    "case_id": case_id,
                    "zone": zone,
                    "triage_level": int(runtime.triage_level or 3),
                    "effective_triage_level": int(runtime.effective_priority or runtime.triage_level or 3),
                    "predicted_diagnosis": _visible_diagnosis(runtime),
                    "predicted_department": str(runtime.target_department).strip(),
                    "diagnosis_correct": False,
                    "department_correct": False,
                    "alerts": self._patient_alerts(runtime),
                    "last_action": str(runtime.latest_action).strip(),
                    "actor": str(runtime.latest_actor).strip(),
                    "assigned_staff": assigned_staff,
                    "movement_target_id": self._movement_target_id(runtime, zone),
                    "current_location_id": str(getattr(runtime, "current_location_id", "")).strip(),
                    "target_location_id": str(getattr(runtime, "target_location_id", "")).strip(),
                    "interaction_location_id": str(getattr(runtime, "interaction_location_id", "")).strip(),
                    "movement_path": [str(item).strip() for item in list(getattr(runtime, "movement_path", []) or []) if str(item).strip()],
                    "pending_interaction": dict(getattr(runtime, "pending_interaction", {}) or {}),
                }
            )
        return patients

    def _runtime_scene_state(
        self,
        state: HospitalSchedulerState,
        patients: list[dict[str, Any]],
        *,
        snapshot_phase: str = "",
        snapshot_action: str = "",
    ) -> dict[str, Any]:
        scene_runtime: dict[str, Any] = {
            "er_beds": {},
            "observation_beds": {},
            "await_slots": {},
            "specialty_consults": {},
            "discharge_slots": {},
            "waiting_seats": {},
            "doctor_pairings": {"er": ""},
            "specialty_calls": {},
            "patient_overrides": {},
            "doctor_overrides": {},
            "nurse_overrides": {},
        }
        waiting_index = 1
        await_index = 1
        discharge_index = 1
        for patient in patients:
            case_id = str(patient.get("case_id", "")).strip()
            zone = str(patient.get("zone", "")).strip()
            target_id = str(patient.get("movement_target_id", "")).strip()
            if zone == "waiting_room":
                if target_id.startswith("arrival_") or target_id.startswith("triage_"):
                    scene_runtime["patient_overrides"][case_id] = target_id
                else:
                    slot_id = f"waiting_chair_{min(waiting_index, 6)}"
                    scene_runtime["waiting_seats"][slot_id] = case_id
                    waiting_index += 1
            elif zone == "er_workup":
                slot_id = target_id or f"er_bed_{min(waiting_index, 4)}"
                scene_runtime["er_beds"][slot_id] = case_id
            elif zone == "awaiting_results":
                slot_id = target_id or ("lab_wait_1" if await_index % 2 else "imaging_wait_1")
                scene_runtime["await_slots"][slot_id] = case_id
                await_index += 1
            elif zone == "specialty_review":
                slot_id = target_id or "specialty_consult_1"
                scene_runtime["specialty_consults"][slot_id] = case_id
            elif zone == "completed":
                slot_id = f"discharge_{min(discharge_index, 3)}"
                scene_runtime["discharge_slots"][slot_id] = case_id
                discharge_index += 1
        for case_id, runtime in state.cases.items():
            workflow = str(runtime.workflow_state).strip()
            nurse_location_id = self._movement_target_id(runtime, self._scheduler_zone(runtime))
            nurse_base_location_id = _nurse_base_location_for_runtime(runtime)
            runtime_current_location = str(getattr(runtime, "current_location_id", "")).strip()
            runtime_target_location = str(getattr(runtime, "target_location_id", "")).strip()
            runtime_interaction_location = str(getattr(runtime, "interaction_location_id", "")).strip()
            runtime_movement_path = [str(item).strip() for item in list(getattr(runtime, "movement_path", []) or []) if str(item).strip()]
            shared_patient_path = runtime_movement_path[:] if runtime_movement_path else [
                runtime_current_location or nurse_base_location_id,
                runtime_target_location or nurse_location_id,
            ]
            if workflow == "in_er_interview":
                scene_runtime["doctor_pairings"]["er"] = case_id
                scene_runtime["doctor_overrides"]["er"] = _bedside_location_for_runtime(runtime)
                scene_runtime["nurse_overrides"][_assigned_nurse_id(runtime)] = {
                    "case_id": case_id,
                    "current_location_id": runtime_interaction_location or nurse_base_location_id,
                    "location_id": _bedside_location_for_runtime(runtime),
                    "interaction_location_id": _bedside_location_for_runtime(runtime),
                    "status": "assist",
                    "movement_path": [runtime_interaction_location or _bedside_location_for_runtime(runtime)],
                    "pending_interaction": dict(getattr(runtime, "pending_interaction", {}) or {}),
                }
            elif workflow == "waiting_er_doctor_arrival":
                scene_runtime["nurse_overrides"][_assigned_nurse_id(runtime)] = {
                    "case_id": case_id,
                    "current_location_id": runtime_current_location or nurse_base_location_id,
                    "location_id": runtime_target_location or _bedside_location_for_runtime(runtime),
                    "interaction_location_id": runtime_interaction_location or _bedside_location_for_runtime(runtime),
                    "status": "assist",
                    "movement_path": shared_patient_path,
                    "pending_interaction": dict(getattr(runtime, "pending_interaction", {}) or {}),
                }
            elif workflow == "waiting_er":
                scene_runtime["nurse_overrides"][_assigned_nurse_id(runtime)] = {
                    "case_id": case_id,
                    "current_location_id": runtime_current_location or nurse_base_location_id,
                    "location_id": runtime_target_location or _bedside_location_for_runtime(runtime),
                    "interaction_location_id": runtime_interaction_location or _bedside_location_for_runtime(runtime),
                    "status": "escort",
                    "movement_path": shared_patient_path,
                    "pending_interaction": {},
                }
            elif workflow == "waiting_test":
                scene_runtime["nurse_overrides"][_assigned_nurse_id(runtime)] = {
                    "case_id": case_id,
                    "current_location_id": runtime_current_location or str(getattr(runtime, "assigned_bed_id", "")).strip() or nurse_base_location_id,
                    "location_id": runtime_target_location or nurse_location_id,
                    "interaction_location_id": runtime_interaction_location or nurse_location_id,
                    "status": "escort",
                    "movement_path": shared_patient_path,
                    "pending_interaction": {},
                }
            elif workflow in {"waiting_triage", "waiting_bed"}:
                scene_runtime["nurse_overrides"][_assigned_nurse_id(runtime)] = {
                    "case_id": case_id,
                    "current_location_id": runtime_current_location or "triage_desk",
                    "location_id": runtime_target_location or nurse_location_id,
                    "interaction_location_id": runtime_interaction_location or nurse_location_id,
                    "status": "escort",
                    "movement_path": shared_patient_path,
                    "pending_interaction": {},
                }
            elif workflow == "awaiting_results":
                scene_runtime["nurse_overrides"][_assigned_nurse_id(runtime)] = {
                    "case_id": case_id,
                    "current_location_id": runtime_current_location or nurse_location_id,
                    "location_id": runtime_target_location or nurse_location_id,
                    "interaction_location_id": runtime_interaction_location or nurse_location_id,
                    "status": "observe",
                    "movement_path": shared_patient_path,
                    "pending_interaction": dict(getattr(runtime, "pending_interaction", {}) or {}),
                }
            elif workflow in {"waiting_specialty", "in_specialty_consult"}:
                scene_runtime["nurse_overrides"][_assigned_nurse_id(runtime)] = {
                    "case_id": case_id,
                    "current_location_id": runtime_current_location or runtime_interaction_location or runtime_target_location or nurse_base_location_id,
                    "location_id": _bedside_location_for_runtime(runtime),
                    "interaction_location_id": _bedside_location_for_runtime(runtime),
                    "status": "assist",
                    "movement_path": shared_patient_path if shared_patient_path else [_bedside_location_for_runtime(runtime)],
                    "pending_interaction": dict(getattr(runtime, "pending_interaction", {}) or {}),
                }
            elif workflow == "completed":
                scene_runtime["nurse_overrides"][_assigned_nurse_id(runtime)] = {
                    "case_id": case_id,
                    "current_location_id": runtime_current_location or _bedside_location_for_runtime(runtime),
                    "location_id": nurse_base_location_id,
                    "interaction_location_id": "",
                    "status": "idle",
                    "movement_path": runtime_movement_path or [runtime_current_location or _bedside_location_for_runtime(runtime), nurse_base_location_id],
                    "pending_interaction": {},
                }
            if workflow in {"waiting_specialty", "in_specialty_consult"} and str(runtime.target_department).strip():
                department = str(runtime.target_department).strip()
                specialist_resource = state.resources.find_by_id(str(getattr(runtime, "assigned_specialist_id", "")).strip())
                scene_runtime["specialty_calls"][department] = {
                    "case_id": case_id,
                    "status": "consulting" if workflow == "in_specialty_consult" else "summoned",
                    "summoned_min": int(state.current_minute or 0),
                    "arrival_min": int(getattr(runtime, "specialty_arrival_min", 0) or state.current_minute or 0),
                    "current_location_id": str(getattr(specialist_resource, "location_id", "")).strip() if specialist_resource is not None else f"sidebar_{department}",
                }
        er_doctor_resource = state.resources.find_by_id("doctor_er_0")
        er_doctor_current_location = str(getattr(er_doctor_resource, "location_id", "")).strip() or "er_doctor_station"
        scene_runtime["doctor_overrides"]["er"] = {
            "current_location_id": er_doctor_current_location,
            "location_id": er_doctor_current_location,
            "interaction_location_id": "",
            "movement_path": [er_doctor_current_location],
        }
        latest_event = dict(state.event_log[-1] if state.event_log else {})
        latest_case_id = str(latest_event.get("case_id", "")).strip()
        latest_action = str(latest_event.get("action", "")).strip()
        latest_runtime = state.cases.get(latest_case_id)
        if latest_runtime is not None:
            bed_id = str(getattr(latest_runtime, "assigned_bed_id", "")).strip() or "er_bed_1"
            latest_nurse_base_location_id = _nurse_base_location_for_runtime(latest_runtime)
            if latest_action in {"dispatch_er", "ask_history", "perform_assessment", "order_test", "request_specialty", "review_results", "await_results"}:
                scene_runtime["doctor_pairings"]["er"] = latest_case_id
                bedside_location = _bedside_location_for_runtime(latest_runtime)
                if latest_action == "dispatch_er":
                    scene_runtime["doctor_overrides"]["er"] = {
                        "current_location_id": er_doctor_current_location,
                        "location_id": bedside_location,
                        "interaction_location_id": bedside_location,
                        "movement_path": [er_doctor_current_location, bedside_location],
                    }
                else:
                    scene_runtime["doctor_overrides"]["er"] = {
                        "current_location_id": er_doctor_current_location,
                        "location_id": bedside_location,
                        "interaction_location_id": bedside_location,
                        "movement_path": [bedside_location],
                    }
            if latest_action in {"consult_started", "specialty_consult", "specialty_finalize"} and str(getattr(latest_runtime, "target_department", "")).strip():
                department = str(getattr(latest_runtime, "target_department", "")).strip()
                specialist_resource = state.resources.find_by_id(str(getattr(latest_runtime, "assigned_specialist_id", "")).strip())
                scene_runtime["specialty_calls"][department] = {
                    "case_id": latest_case_id,
                    "status": "consulting",
                    "summoned_min": int(state.current_minute or 0),
                    "arrival_min": int(getattr(latest_runtime, "specialty_arrival_min", 0) or state.current_minute or 0),
                    "current_location_id": str(getattr(specialist_resource, "location_id", "")).strip() if specialist_resource is not None else f"sidebar_{department}",
                }
            if latest_action in {"specialty_finalize", "er_finalize"} and str(snapshot_action).strip() != "completed":
                scene_runtime["patient_overrides"][latest_case_id] = _bedside_location_for_runtime(latest_runtime)
                scene_runtime["nurse_overrides"][_assigned_nurse_id(latest_runtime)] = {
                    "case_id": latest_case_id,
                    "current_location_id": str(getattr(latest_runtime, "current_location_id", "")).strip() or latest_nurse_base_location_id,
                    "location_id": _bedside_location_for_runtime(latest_runtime),
                    "interaction_location_id": _bedside_location_for_runtime(latest_runtime),
                    "status": "assist",
                    "movement_path": [
                        str(getattr(latest_runtime, "current_location_id", "")).strip() or latest_nurse_base_location_id,
                        _bedside_location_for_runtime(latest_runtime),
                    ],
                    "pending_interaction": dict(getattr(latest_runtime, "pending_interaction", {}) or {}),
                }
        return scene_runtime

    def _dialogue_for_runtime(self, runtime: Any) -> dict[str, Any]:
        lines: list[str] = []
        sequence: list[dict[str, Any]] = []
        actor = str(runtime.latest_actor).strip()
        action = str(runtime.latest_action).strip()
        case_id = str(runtime.case_id).strip()
        patient_entity_id = f"patient_{case_id}"
        interaction_location_id = _dialogue_interaction_location(runtime, action)
        if action == "ask_history" and list(runtime.question_history):
            qa = dict(list(runtime.question_history)[-1] or {})
            question = str(qa.get("question", "")).strip()
            answer = str(qa.get("answer", "")).strip()
            if question:
                lines.append(f"ER: {question}")
                sequence.append(
                    {
                        "speaker": "ER",
                        "text": question,
                        "speaker_entity_id": "doctor_er_0",
                        "listener_entity_id": patient_entity_id,
                        "delay_ms": 0,
                        "interaction_location_id": interaction_location_id,
                    }
                )
            if answer:
                lines.append(f"Patient: {answer}")
                sequence.append(
                    {
                        "speaker": "Patient",
                        "text": answer,
                        "speaker_entity_id": patient_entity_id,
                        "listener_entity_id": "doctor_er_0",
                        "delay_ms": 2000,
                        "interaction_location_id": interaction_location_id,
                    }
                )
        elif action == "request_specialty":
            department = str(runtime.target_department).strip().replace("_", " ") or "specialist"
            department_label = department.title()
            lines.append(f"ER: Calling {department_label} to the ER now.")
            lines.append(f"{department_label}: I'm on my way.")
            sequence.extend(
                [
                    {
                        "speaker": "ER",
                        "text": f"Calling {department_label} to the ER now.",
                        "speaker_entity_id": "doctor_er_0",
                        "listener_entity_id": f"specialty_{str(runtime.target_department).strip()}",
                        "delay_ms": 0,
                        "interaction_location_id": interaction_location_id,
                    },
                    {
                        "speaker": department_label,
                        "text": "I'm on my way.",
                        "speaker_entity_id": f"specialty_{str(runtime.target_department).strip()}",
                        "listener_entity_id": "doctor_er_0",
                        "delay_ms": 2000,
                        "interaction_location_id": interaction_location_id,
                    },
                ]
            )
        elif action in {"specialty_consult", "consult_started"}:
            department = str(runtime.target_department).strip().replace("_", " ") or "specialist"
            department_label = department.title()
            patient_line = self._patient_summary_line(runtime)
            lines.append(f"{department_label}: I need to confirm your symptoms directly.")
            lines.append(f"Patient: {patient_line}")
            sequence.extend(
                [
                    {
                        "speaker": department_label,
                        "text": "I need to confirm your symptoms directly.",
                        "speaker_entity_id": f"specialty_{str(runtime.target_department).strip()}",
                        "listener_entity_id": patient_entity_id,
                        "delay_ms": 0,
                        "interaction_location_id": interaction_location_id,
                    },
                    {
                        "speaker": "Patient",
                        "text": patient_line,
                        "speaker_entity_id": patient_entity_id,
                        "listener_entity_id": f"specialty_{str(runtime.target_department).strip()}",
                        "delay_ms": 2000,
                        "interaction_location_id": interaction_location_id,
                    },
                ]
            )
        elif action == "specialty_finalize" and list(runtime.consult_history):
            consult = dict(list(runtime.consult_history)[-1] or {})
            opinion = str(consult.get("opinion", "")).strip()
            if opinion:
                lines.append(f"Specialist: {opinion}")
                sequence.append(
                    {
                        "speaker": "Specialist",
                        "text": opinion,
                        "speaker_entity_id": f"specialty_{str(runtime.target_department).strip()}",
                        "listener_entity_id": patient_entity_id,
                        "delay_ms": 0,
                        "interaction_location_id": interaction_location_id,
                    }
                )
        elif action == "order_test" and list(runtime.recommended_tests):
            test_name = str(runtime.recommended_tests[0]).strip()
            lines.append(f"ER: We need {test_name} to clarify this case.")
            sequence.append(
                {
                    "speaker": "ER",
                    "text": f"We need {test_name} to clarify this case.",
                    "speaker_entity_id": "doctor_er_0",
                    "listener_entity_id": patient_entity_id,
                    "delay_ms": 0,
                    "interaction_location_id": interaction_location_id,
                }
            )
        elif action == "test_result_ready" and list(getattr(runtime, "test_results", []) or []):
            result = dict(list(getattr(runtime, "test_results", []) or [])[-1] or {})
            test_name = str(result.get("test_name", "")).strip() or "Test"
            impression = str(result.get("impression", "")).strip()
            lines.append(f"ER: {test_name} results are back.")
            if impression:
                lines.append(f"ER: {impression}")
            sequence.append(
                {
                    "speaker": "ER",
                    "text": f"{test_name} results are back.",
                    "speaker_entity_id": "doctor_er_0",
                    "listener_entity_id": patient_entity_id,
                    "delay_ms": 0,
                    "interaction_location_id": interaction_location_id,
                }
            )
            if impression:
                sequence.append(
                    {
                        "speaker": "ER",
                        "text": impression,
                        "speaker_entity_id": "doctor_er_0",
                        "listener_entity_id": patient_entity_id,
                        "delay_ms": 2000,
                        "interaction_location_id": interaction_location_id,
                    }
                )
        elif action == "er_finalize":
            lines.append("ER: We now have enough evidence to finalize your ER assessment.")
            diagnosis = str(runtime.assessment_summary).strip()
            if diagnosis:
                lines.append(f"ER: Working diagnosis is {diagnosis}.")
            sequence.append(
                {
                    "speaker": "ER",
                    "text": "We now have enough evidence to finalize your ER assessment.",
                    "speaker_entity_id": "doctor_er_0",
                    "listener_entity_id": patient_entity_id,
                    "delay_ms": 0,
                    "interaction_location_id": interaction_location_id,
                }
            )
            if diagnosis:
                sequence.append(
                    {
                        "speaker": "ER",
                        "text": f"Working diagnosis is {diagnosis}.",
                        "speaker_entity_id": "doctor_er_0",
                        "listener_entity_id": patient_entity_id,
                        "delay_ms": 2000,
                        "interaction_location_id": interaction_location_id,
                    }
                )

        if not lines:
            return {
                "case_id": "",
                "actor": "",
                "action": "",
                "lines": [],
                "sequence": [],
                "speaker_entity_id": "",
                "listener_entity_id": "",
                "bubble_text": "",
                "interaction_location_id": "",
            }

        normalized_actor = "er_department" if actor.startswith("doctor_er") else actor.replace("specialty_", "")
        speaker = "doctor_er_0" if normalized_actor == "er_department" else f"specialty_{normalized_actor}"
        return {
            "case_id": case_id,
            "actor": normalized_actor,
            "action": action,
            "lines": lines[-2:],
            "sequence": sequence[-4:],
            "speaker_entity_id": speaker,
            "listener_entity_id": patient_entity_id,
            "bubble_text": lines[-1].split(": ", 1)[-1][:72],
            "interaction_location_id": interaction_location_id,
        }

    def _empty_dialogue(self) -> dict[str, Any]:
        return {
            "case_id": "",
            "actor": "",
            "action": "",
            "lines": [],
            "sequence": [],
            "speaker_entity_id": "",
            "listener_entity_id": "",
            "bubble_text": "",
            "interaction_location_id": "",
        }

    def _dialogue_from_event(self, state: HospitalSchedulerState, event: dict[str, Any]) -> dict[str, Any]:
        event_id = str(event.get("event_id", "")).strip()
        if not event_id or event_id == self._last_dialogue_event_id:
            return self._empty_dialogue()
        case_id = str(event.get("case_id", "")).strip()
        runtime = state.cases.get(case_id)
        if runtime is None:
            return self._empty_dialogue()
        action = str(event.get("action", "")).strip()
        conversational_actions = {
            "ask_history",
            "request_specialty",
            "consult_started",
            "specialty_finalize",
            "order_test",
            "test_result_ready",
            "er_finalize",
        }
        if action not in conversational_actions:
            return self._empty_dialogue()
        if not _dialogue_ready_for_runtime(runtime, action, int(state.current_minute or 0)):
            return self._empty_dialogue()
        dialogue = self._dialogue_for_runtime(runtime)
        if str(dialogue.get("action", "")).strip() != action:
            actor_id = self._event_actor_id(event)
            payload = dict(event.get("payload", {}) or {})
            patient_entity_id = f"patient_{case_id}"
            if action == "request_specialty":
                department = str(payload.get("department", getattr(runtime, "target_department", ""))).strip().replace("_", " ") or "specialist"
                department_key = str(getattr(runtime, "target_department", "")).strip()
                department_label = department.title()
                dialogue = {
                    "case_id": case_id,
                    "actor": "er_department",
                    "action": "request_specialty",
                    "lines": [
                        f"ER: Calling {department_label} to the ER now.",
                        f"{department_label}: I'm on my way.",
                    ],
                    "sequence": [
                        {
                            "speaker": "ER",
                            "text": f"Calling {department_label} to the ER now.",
                            "speaker_entity_id": "doctor_er_0",
                            "listener_entity_id": f"specialty_{department_key}",
                            "delay_ms": 0,
                            "interaction_location_id": "",
                        },
                        {
                            "speaker": department_label,
                            "text": "I'm on my way.",
                            "speaker_entity_id": f"specialty_{department_key}",
                            "listener_entity_id": "doctor_er_0",
                            "delay_ms": 2000,
                            "interaction_location_id": "",
                        },
                    ],
                    "speaker_entity_id": "doctor_er_0",
                    "listener_entity_id": patient_entity_id,
                    "bubble_text": "I'm on my way.",
                    "interaction_location_id": "",
                }
            elif action == "consult_started":
                department = str(payload.get("department", getattr(runtime, "target_department", ""))).strip().replace("_", " ") or "specialist"
                department_label = department.title()
                patient_line = self._patient_summary_line(runtime)
                speaker_entity_id = actor_id or f"specialty_{str(getattr(runtime, 'target_department', '')).strip()}"
                dialogue = {
                    "case_id": case_id,
                    "actor": str(speaker_entity_id).replace("specialty_", ""),
                    "action": "consult_started",
                    "lines": [
                        f"{department_label}: I need to confirm your symptoms directly.",
                        f"Patient: {patient_line}",
                    ],
                    "sequence": [
                        {
                            "speaker": department_label,
                            "text": "I need to confirm your symptoms directly.",
                            "speaker_entity_id": speaker_entity_id,
                            "listener_entity_id": patient_entity_id,
                            "delay_ms": 0,
                            "interaction_location_id": _dialogue_interaction_location(runtime, "consult_started"),
                        },
                        {
                            "speaker": "Patient",
                            "text": patient_line,
                            "speaker_entity_id": patient_entity_id,
                            "listener_entity_id": speaker_entity_id,
                            "delay_ms": 2000,
                            "interaction_location_id": _dialogue_interaction_location(runtime, "consult_started"),
                        },
                    ],
                    "speaker_entity_id": speaker_entity_id,
                    "listener_entity_id": patient_entity_id,
                    "bubble_text": patient_line[:72],
                    "interaction_location_id": _dialogue_interaction_location(runtime, "consult_started"),
                }
        if list(dialogue.get("lines", []) or []):
            self._last_dialogue_event_id = event_id
        return dialogue

    def _remember_conversation(self, dialogue: dict[str, Any], current_time_min: int) -> None:
        lines = [str(line).strip() for line in list(dialogue.get("lines", []) or []) if str(line).strip()]
        if not lines:
            return
        signature = (
            str(dialogue.get("actor", "")).strip(),
            str(dialogue.get("case_id", "")).strip(),
            tuple(lines),
        )
        if signature in self._recent_signatures:
            return
        self._recent_signatures.append(signature)
        self._recent_signatures = self._recent_signatures[-24:]
        self.conversation_history.append(
            {
                "minute": int(current_time_min or 0),
                "actor": str(dialogue.get("actor", "")).strip(),
                "case_id": str(dialogue.get("case_id", "")).strip(),
                "action": str(dialogue.get("action", "")).strip(),
                "lines": lines,
            }
        )
        self.conversation_history = self.conversation_history[-20:]

    def _event_payload(self, runtime: Any, action: str) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if action == "ask_history" and list(runtime.question_history):
            qa = dict(list(runtime.question_history)[-1] or {})
            payload["question"] = str(qa.get("question", "")).strip()
            payload["answer"] = str(qa.get("answer", "")).strip()
        if action == "order_test" and list(runtime.recommended_tests):
            payload["requested_test"] = str(runtime.recommended_tests[0]).strip()
        if action == "test_result_ready" and list(getattr(runtime, "test_results", []) or []):
            payload["test_result"] = dict(list(getattr(runtime, "test_results", []) or [])[-1] or {})
        if action in {"specialty_consult", "specialty_finalize"}:
            payload["department"] = str(runtime.target_department).strip()
        if action in {"er_finalize", "specialty_finalize"}:
            payload["diagnosis"] = str(runtime.assessment_summary).strip()
            payload["final_department"] = str(runtime.target_department).strip()
        payload["pending_results_count"] = len(list(runtime.pending_results or []))
        return payload

    def _event_scene_context(self, runtime: Any, action: str) -> tuple[str, str, str]:
        normalized = str(action).strip()
        if normalized == "arrival_entered":
            return "waiting_room", "arrival_entry_1", ""
        if normalized == "perform_triage":
            return "waiting_room", "triage_desk", ""
        if normalized == "dispatch_er":
            return "er_workup", str(getattr(runtime, "assigned_bed_id", "")).strip() or "er_bed_1", ""
        if normalized in {"bed_assigned", "ask_history"}:
            return "er_workup", str(getattr(runtime, "assigned_bed_id", "")).strip() or "er_bed_1", ""
        if normalized == "order_test":
            tests = list(getattr(runtime, "recommended_tests", []) or [])
            test_name = str(tests[0]).strip().lower() if tests else ""
            location_id = "imaging_wait_1" if any(token in test_name for token in ("mri", "ct", "xray", "x-ray", "imaging")) else "lab_wait_1"
            return "awaiting_results", location_id, "test"
        if normalized == "test_started":
            pending = list(getattr(runtime, "pending_results", []) or [])
            resource_type = str(dict(pending[0]).get("resource_type", "")).strip() if pending else ""
            location_id = "imaging_wait_1" if resource_type == "imaging_slot" else "lab_wait_1"
            return "awaiting_results", location_id, "test"
        if normalized == "test_result_ready":
            return "er_workup", str(getattr(runtime, "assigned_bed_id", "")).strip() or "er_bed_1", "test"
        if normalized == "request_specialty":
            return "er_workup", str(getattr(runtime, "assigned_bed_id", "")).strip() or "er_bed_1", ""
        if normalized in {"specialty_consult", "consult_started"}:
            return "er_workup", str(getattr(runtime, "assigned_bed_id", "")).strip() or "er_bed_1", "consult"
        if normalized in {"specialty_finalize", "er_finalize"}:
            return "completed", "discharge_1", "consult" if normalized == "specialty_finalize" else ""
        return self._scheduler_zone(runtime), self._movement_target_id(runtime, self._scheduler_zone(runtime)), ""

    @staticmethod
    def _event_actor_id(event: dict[str, Any]) -> str:
        actor = event.get("actor", {})
        if isinstance(actor, dict):
            return str(actor.get("id", "")).strip()
        return str(actor).strip()

    @staticmethod
    def _event_actor_role(event: dict[str, Any]) -> str:
        actor = event.get("actor", {})
        if isinstance(actor, dict):
            return str(actor.get("role", "")).strip()
        return ""

    @staticmethod
    def _event_target_payload(event: dict[str, Any], case_id: str) -> dict[str, Any]:
        target = event.get("target", {})
        if isinstance(target, dict) and target:
            return {
                "id": str(target.get("id", "")).strip(),
                "role": str(target.get("role", "")).strip(),
                "label": str(target.get("label", "")).strip(),
            }
        return {
            "id": f"patient_{case_id}" if case_id else "",
            "role": "patient",
            "label": "",
        }

    def _event_entry(self, state: HospitalSchedulerState, event: dict[str, Any], index: int) -> dict[str, Any]:
        event_dict = dict(event or {})
        case_id = str(event_dict.get("case_id", "")).strip()
        runtime = state.cases.get(case_id)
        action = str(event_dict.get("action", "")).strip()
        actor_id = self._event_actor_id(event_dict)
        actor_role = self._event_actor_role(event_dict)
        payload = dict(event_dict.get("payload", {}) or {})
        if not payload and runtime is not None:
            payload = self._event_payload(runtime, action)
        fallback_zone, fallback_location_id, fallback_resource_kind = (
            self._event_scene_context(runtime, action) if runtime is not None else ("", "", "")
        )
        state_delta = dict(event_dict.get("state_delta", {}) or {})
        zone = str(event_dict.get("zone", "")).strip() or str(state_delta.get("zone", "")).strip() or fallback_zone
        location_id = str(event_dict.get("location_id", "")).strip() or fallback_location_id
        resource_kind = str(event_dict.get("resource_kind", "")).strip() or fallback_resource_kind or actor_role
        return {
            "event_id": str(event_dict.get("event_id", "")).strip() or f"parallel_{index}_{case_id}_{action}",
            "run_id": str(event_dict.get("run_id", "")).strip() or str(state.run_id).strip(),
            "minute": int(event_dict.get("minute", 0) or 0),
            "tick": int(event_dict.get("tick", 0) or 0),
            "phase": str(event_dict.get("phase", "")).strip() or action,
            "event_type": str(event_dict.get("event_type", "")).strip() or action,
            "action": action,
            "location_id": location_id,
            "resource_kind": resource_kind,
            "rationale": str(event_dict.get("rationale", "")).strip(),
            "payload": payload,
            "state_delta": {
                **state_delta,
                "zone": zone,
                "pending_results_count": int(
                    state_delta.get("pending_results_count", payload.get("pending_results_count", 0)) or 0
                ),
            },
            "zone": zone,
            "actor": {
                "id": actor_id,
                "role": actor_role or ("er" if actor_id.startswith("doctor_er") else ("specialty" if actor_id.startswith("specialty_") else "system")),
            },
            "target": self._event_target_payload(event_dict, case_id),
        }

    def _event_log_recent(self, state: HospitalSchedulerState, limit: int = 40) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        recent_source = list(state.event_log or [])[-limit:]
        for index, event in enumerate(recent_source):
            events.append(self._event_entry(state, dict(event or {}), index))
        return events[-limit:]

    def _er_focus(self, state: HospitalSchedulerState) -> dict[str, Any]:
        active = None
        for runtime in state.cases.values():
            if str(runtime.workflow_state).strip() in {"in_er_interview", "waiting_test", "awaiting_results", "waiting_er", "waiting_er_doctor_arrival"}:
                active = runtime
                break
        if active is None:
            return {
                "case_id": "",
                "action": "",
                "zone": "",
                "triage_level": 0,
                "effective_triage_level": 0,
                "deterioration_risk": "",
                "pending_results_count": 0,
                "observation_status": "",
            "working_diagnosis": "",
            "responsible_department": "",
        }
        return {
            "case_id": str(active.case_id).strip(),
            "action": str(active.latest_action).strip(),
            "zone": self._scheduler_zone(active),
            "triage_level": int(active.triage_level or 3),
            "effective_triage_level": int(active.effective_priority or active.triage_level or 3),
            "deterioration_risk": str(active.deterioration_risk).strip(),
            "pending_results_count": len(list(active.pending_results or [])),
            "observation_status": "",
            "working_diagnosis": _visible_diagnosis(active),
            "responsible_department": str(active.target_department).strip(),
        }

    def _case_detail(self, state: HospitalSchedulerState, runtime: Any) -> dict[str, Any]:
        demo_meta = dict(dict(runtime.case_data.get("meta", {}) or {}).get("demo", {}) or {})
        recent_events = [
            self._event_entry(state, dict(event or {}), index)
            for index, event in enumerate(list(state.event_log or []))
            if str(dict(event or {}).get("case_id", "")).strip() == str(runtime.case_id).strip()
        ][-8:]
        current_event = {}
        if recent_events:
            latest = dict(recent_events[-1] or {})
            current_event = {
                "minute": int(latest.get("minute", 0) or 0),
                "event_type": str(latest.get("event_type", "")).strip(),
                "action": str(latest.get("action", "")).strip(),
                "label": str(latest.get("action", "")).replace("_", " ").strip(),
                "rationale": str(latest.get("rationale", "")).strip(),
                "payload": dict(latest.get("payload", {}) or {}),
            }
        decision_points = [dict(item or {}) for item in list(runtime.decision_snapshots or []) if dict(item or {})]
        alternatives: list[dict[str, Any]] = []
        recommended_tests = [str(item).strip() for item in list(runtime.recommended_tests or []) if str(item).strip()]
        should_offer_decisions = (
            str(runtime.workflow_state).strip() in {"waiting_er", "in_er_interview", "waiting_test", "awaiting_results", "completed"}
            or bool(recent_events)
        )
        if should_offer_decisions:
            primary_what_if = dict(demo_meta.get("primary_what_if", {}) or {})
            if primary_what_if:
                alternatives.append(
                    {
                        "type": str(primary_what_if.get("type", "")).strip(),
                        "target": str(primary_what_if.get("target", "")).strip(),
                        "rationale": str(primary_what_if.get("impact", "")).strip()
                        or str(primary_what_if.get("label", "")).strip()
                        or "Replay the main presentation what-if branch for this patient.",
                        "label": str(primary_what_if.get("label", "")).strip(),
                    }
                )
            if list(runtime.pending_results or []):
                pending_test_name = str(dict(runtime.pending_results[0] or {}).get("test_name", "")).strip()
                if pending_test_name:
                    alternatives.append(
                        {
                            "type": "await_results",
                            "target": pending_test_name,
                            "rationale": "Hold the current plan, wait for the pending objective result, then reassess.",
                        }
                    )
            alternatives.append(
                {
                    "type": "ask_patient",
                    "target": "focused_history",
                    "rationale": "Gather one more targeted question if symptoms remain ambiguous.",
                }
            )
            if recommended_tests:
                alternatives.append(
                    {
                        "type": "request_test",
                        "target": recommended_tests[0],
                        "rationale": "Order the next lowest-cost targeted objective test.",
                    }
                )
            if str(runtime.target_department).strip() and str(runtime.target_department).strip() not in {"general_medicine", "internal_medicine"}:
                alternatives.append(
                    {
                        "type": "consult_specialty",
                        "target": str(runtime.target_department).strip(),
                        "rationale": "Escalate to the leading specialty when ER ownership is no longer sufficient.",
                    }
                )
            alternatives.append(
                {
                    "type": "diagnose",
                    "target": str(runtime.assessment_summary).strip(),
                    "rationale": "Finalize immediately if current evidence is already decisive enough.",
                }
            )
        deduped_alternatives: list[dict[str, Any]] = []
        seen_alternatives: set[tuple[str, str]] = set()
        for candidate in alternatives:
            key = (str(candidate.get("type", "")).strip(), str(candidate.get("target", "")).strip())
            if key in seen_alternatives:
                continue
            seen_alternatives.add(key)
            deduped_alternatives.append(candidate)
        alternatives = deduped_alternatives
        if alternatives and not decision_points:
            decision_snapshot_id = f"parallel_{str(runtime.case_id).strip()}_m{int(state.current_minute or 0)}"
            decision_points.append(
                {
                    "snapshot_id": decision_snapshot_id,
                    "node": "parallel_scheduler_decision",
                    "turn_index": int(runtime.er_turn_count or 0),
                    "proposed_type": str(runtime.latest_action).strip() or "perform_assessment",
                    "proposed_target": str(runtime.target_department).strip() or (recommended_tests[0] if recommended_tests else ""),
                    "alternatives_count": len(alternatives),
                    "alternatives": alternatives,
                }
            )
        merged_candidates: list[dict[str, Any]] = []
        seen_candidate_keys: set[tuple[str, str]] = set()
        latest_decision_alternatives = list(dict(decision_points[-1] or {}).get("alternatives", []) or []) if decision_points else []
        for candidate in [*latest_decision_alternatives, *alternatives]:
            key = (str(candidate.get("type", "")).strip(), str(candidate.get("target", "")).strip())
            if key in seen_candidate_keys:
                continue
            seen_candidate_keys.add(key)
            merged_candidates.append(candidate)
        return {
            "case_id": str(runtime.case_id).strip(),
            "zone": self._scheduler_zone(runtime),
            "triage_level": int(runtime.triage_level or 3),
            "effective_triage_level": int(runtime.effective_priority or runtime.triage_level or 3),
            "deterioration_risk": str(runtime.deterioration_risk).strip(),
            "predicted_department": str(runtime.target_department).strip(),
            "predicted_diagnosis": _visible_diagnosis(runtime),
            "pending_results_count": len(list(runtime.pending_results or [])),
            "current_location_id": str(getattr(runtime, "current_location_id", "")).strip(),
            "target_location_id": str(getattr(runtime, "target_location_id", "")).strip(),
            "interaction_location_id": str(getattr(runtime, "interaction_location_id", "")).strip(),
            "pending_interaction": dict(getattr(runtime, "pending_interaction", {}) or {}),
            "test_results": [dict(item or {}) for item in list(getattr(runtime, "test_results", []) or [])[-4:]],
            "objective_findings": [str(item).strip() for item in list(runtime.objective_findings or []) if str(item).strip()][-6:],
            "questions": [
                {
                    "question": str(dict(item).get("question", "")).strip(),
                    "answer": str(dict(item).get("answer", "")).strip(),
                }
                for item in list(runtime.question_history or [])[-4:]
            ],
            "tests": [str(item).strip() for item in list(runtime.recommended_tests or []) if str(item).strip()][-6:],
            "decision_points": decision_points,
            "counterfactual_candidates": merged_candidates if decision_points else alternatives[:],
            "what_if_stats": {
                "decision_snapshot_count": len(decision_points),
                "shadow_disagreement_count": 0,
            },
            "wait_escalation_steps": max(0, int(runtime.triage_level or 3) - int(runtime.effective_priority or runtime.triage_level or 3)),
            "alerts": self._patient_alerts(runtime),
            "recent_events": recent_events,
            "current_event": current_event,
            "demo_role": str(demo_meta.get("role", "")).strip(),
            "primary_what_if": dict(demo_meta.get("primary_what_if", {}) or {}),
            "expected_er_path": [str(item).strip() for item in list(demo_meta.get("expected_er_path", []) or []) if str(item).strip()],
        }

    def _resource_occupancy(self, state: HospitalSchedulerState) -> list[dict[str, Any]]:
        occupancy: list[dict[str, Any]] = []
        for collection_name, collection in (
            ("er_doctor", state.resources.er_doctors),
            ("lab_slot", state.resources.lab_slots),
            ("imaging_slot", state.resources.imaging_slots),
            ("specialist", state.resources.specialists),
        ):
            for resource in collection:
                if str(resource.status).strip() != "busy":
                    continue
                occupancy.append(
                    {
                        "case_id": str(resource.assigned_case_id).strip(),
                        "resource_kind": collection_name,
                        "action": "busy",
                        "target": str(resource.location_id).strip(),
                        "start_time_min": max(0, int(state.current_minute or 0) - 1),
                        "end_time_min": int(resource.available_minute or state.current_minute or 0),
                    }
                )
        return occupancy

    def _world_snapshot(
        self,
        *,
        current_time_min: int,
        patients: list[dict[str, Any]],
        resource_occupancy: list[dict[str, Any]],
        case_details: dict[str, Any],
        scene_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        rooms = []
        for zone_name in ZONE_ORDER:
            occupants = [str(patient.get("case_id", "")).strip() for patient in patients if str(patient.get("zone", "")).strip() == zone_name]
            rooms.append(
                {
                    "room_id": zone_name,
                    "room_type": zone_name,
                    "activity_label": zone_name.replace("_", " "),
                    "occupants": occupants,
                    "active_case_ids": occupants,
                }
            )
        queues = [
            {
                "queue_id": "arrival_queue",
                "case_ids": list(state_case_id for state_case_id in []),
                "priority_mode": self.queue_policy,
                "last_updated_minute": int(current_time_min or 0),
            }
        ]
        cases = []
        for patient in patients:
            case_id = str(patient.get("case_id", "")).strip()
            detail = dict(case_details.get(case_id, {}) or {})
            cases.append(
                {
                    "case_id": case_id,
                    "zone": str(patient.get("zone", "")).strip(),
                    "triage_level": int(patient.get("triage_level", 3) or 3),
                    "effective_triage_level": int(patient.get("effective_triage_level", 3) or 3),
                    "current_owner": str(patient.get("assigned_staff", "")).strip(),
                    "current_location_id": str(patient.get("current_location_id", "")).strip() or str(patient.get("movement_target_id", "")).strip(),
                    "target_location_id": str(patient.get("target_location_id", "")).strip() or str(patient.get("movement_target_id", "")).strip(),
                    "interaction_location_id": str(patient.get("interaction_location_id", "")).strip(),
                    "pending_interaction": dict(detail.get("pending_interaction", {}) or patient.get("pending_interaction", {}) or {}),
                    "pending_tests": list(detail.get("tests", []) or []),
                    "pending_results_count": int(detail.get("pending_results_count", 0) or 0),
                    "questions": list(detail.get("questions", []) or []),
                    "objective_findings": list(detail.get("objective_findings", []) or []),
                    "predicted_department": str(detail.get("predicted_department", "")).strip(),
                    "predicted_diagnosis": str(detail.get("predicted_diagnosis", "")).strip(),
                    "finalized": str(patient.get("zone", "")).strip() == "completed",
                }
            )
        return {
            "actors": list(dict(scene_snapshot or {}).get("entities", []) or []),
            "rooms": rooms,
            "resources": list(resource_occupancy),
            "queues": queues,
            "cases": cases,
        }

    def _write_snapshot(self, state: HospitalSchedulerState, *, phase: str, actor: str, action: str) -> None:
        patients = self._patients(state)
        scene_runtime = self._runtime_scene_state(
            state,
            patients,
            snapshot_phase=phase,
            snapshot_action=action,
        )
        case_state_map = {
            str(runtime.case_id).strip(): {
                "case_id": str(runtime.case_id).strip(),
                "phase": str(runtime.workflow_state).strip(),
                "actor": "er_department" if str(runtime.latest_actor).startswith("doctor_er") else str(runtime.latest_actor).replace("specialty_", ""),
                "action": str(runtime.latest_action).strip(),
                "target": str(runtime.target_department).strip(),
                "queue_context": {
                    "triage_level": int(runtime.triage_level or 3),
                    "deterioration_risk": str(runtime.deterioration_risk).strip(),
                    "dynamic_priority": {
                        "effective_triage_level": int(runtime.effective_priority or runtime.triage_level or 3),
                        "wait_escalation_steps": max(0, int(runtime.triage_level or 3) - int(runtime.effective_priority or runtime.triage_level or 3)),
                    },
                },
                "assigned_bed_id": str(runtime.assigned_bed_id).strip(),
                "state": {
                    "current_time_min": int(state.current_minute or 0),
                    "pending_results": list(runtime.pending_results or []),
                    "objective_findings": list(runtime.objective_findings or []),
                    "deterioration_risk": str(runtime.deterioration_risk).strip(),
                    "current_location_id": str(getattr(runtime, "current_location_id", "")).strip(),
                    "target_location_id": str(getattr(runtime, "target_location_id", "")).strip(),
                    "interaction_location_id": str(getattr(runtime, "interaction_location_id", "")).strip(),
                    "movement_path": [str(item).strip() for item in list(getattr(runtime, "movement_path", []) or []) if str(item).strip()],
                    "pending_interaction": dict(getattr(runtime, "pending_interaction", {}) or {}),
                    "trajectory_steps": [
                        {
                            "action": "ask_patient",
                            "outcome": {
                                "question": str(dict(item).get("question", "")).strip(),
                                "answer": str(dict(item).get("answer", "")).strip(),
                            },
                        }
                        for item in list(runtime.question_history or [])
                    ],
                    "event_log": [],
                },
                "transcript_tail": [],
                "conversation_lines": [],
            }
            for runtime in state.cases.values()
            if str(runtime.workflow_state).strip() != "not_arrived"
        }
        scene_snapshot = build_hospital_scene_snapshot(
            patients=patients,
            case_state_map=case_state_map,
            runtime_scene_state=scene_runtime,
            current_time_min=int(state.current_minute or 0),
        )
        latest_event = dict(state.event_log[-1] if state.event_log else {})
        dialogue = self._dialogue_from_event(state, latest_event) if latest_event else self._empty_dialogue()
        self._remember_conversation(dialogue, int(state.current_minute or 0))
        case_details = {
            str(runtime.case_id).strip(): self._case_detail(state, runtime)
            for runtime in state.cases.values()
            if str(runtime.workflow_state).strip() != "not_arrived"
        }
        resource_occupancy = self._resource_occupancy(state)
        zones = {zone: [patient for patient in patients if str(patient.get("zone", "")).strip() == zone] for zone in ZONE_ORDER}
        snapshot = {
            "run_id": self.run_id,
            "queue_policy": self.queue_policy,
            "current_time_min": int(state.current_minute or 0),
            "snapshot_written_at_unix": time.time(),
            "phase": phase,
            "actor": actor,
            "action": action,
            "simulation_status": "completed" if phase == "completed" else "running",
            "zones": zones,
            "patients": patients,
            "resource_occupancy": resource_occupancy,
            "completed_count": len([runtime for runtime in state.cases.values() if bool(runtime.is_completed)]),
            "waiting_count": len(zones.get("waiting_room", [])),
            "dialogue": dialogue,
            "conversation_history": list(self.conversation_history),
            "conversation_log_recent": list(self.conversation_history[-20:]),
            "event_log_recent": self._event_log_recent(state),
            "er_focus": self._er_focus(state),
            "case_details": case_details,
            "scene": scene_snapshot,
            "demo": dict(self.demo_context or {}),
        }
        display_minute_limit = int(dict(self.demo_context or {}).get("display_minute_limit", 0) or 0)
        snapshot["display_time_min"] = min(int(state.current_minute or 0), display_minute_limit) if display_minute_limit > 0 else int(state.current_minute or 0)
        snapshot["post_demo_wrap_up"] = bool(display_minute_limit > 0 and int(state.current_minute or 0) > display_minute_limit)
        snapshot["world"] = self._world_snapshot(
            current_time_min=int(state.current_minute or 0),
            patients=patients,
            resource_occupancy=resource_occupancy,
            case_details=case_details,
            scene_snapshot=scene_snapshot,
        )
        self.history.append(snapshot)
        self._atomic_write_json(self.snapshot_path, snapshot)
        self._atomic_write_json(self.history_path, self.history)
        if self.step_delay_sec > 0 and phase not in {"initialized", "completed"}:
            time.sleep(self.step_delay_sec)
