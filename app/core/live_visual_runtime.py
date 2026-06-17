from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from app.config import settings
from app.core.hospital_scene_builder import build_hospital_scene_snapshot, load_hospital_scene_layout
from app.core.logger import get_run_dir


ZONE_ORDER = [
    "waiting_room",
    "er_workup",
    "observation",
    "awaiting_results",
    "specialty_review",
    "completed",
]


def _assigned_slot_name(scene_runtime: dict[str, Any], case_id: str) -> str:
    for key in ("waiting_seats", "er_beds", "observation_beds", "await_slots", "specialty_consults", "discharge_slots"):
        slot_map = dict(scene_runtime.get(key, {}) or {})
        for slot_id, assigned_case_id in slot_map.items():
            if assigned_case_id == case_id:
                return str(slot_id).strip()
    return ""


class LiveVisualRuntimeWriter:
    def __init__(self, run_id: str, queue_policy: str, step_delay_sec: float | None = None) -> None:
        self.run_id = run_id
        self.queue_policy = queue_policy
        self.layout = load_hospital_scene_layout()
        delay_from_env = float(os.getenv("LIVE_VIS_STEP_DELAY_SEC", "0.55") or 0.55)
        self.step_delay_sec = delay_from_env if step_delay_sec is None else max(0.0, float(step_delay_sec))
        self.report_dir = get_run_dir(settings.REPORTS_DIR, run_id)
        self.snapshot_path = self.report_dir / "live_visual_state.json"
        self.history_path = self.report_dir / "live_visual_history.json"
        self.queue_items: list[dict[str, Any]] = []
        self.completed_case_ids: set[str] = set()
        self.case_state_map: dict[str, dict[str, Any]] = {}
        self.current_payload: dict[str, Any] = {}
        self.history: list[dict[str, Any]] = []
        self.conversation_history: list[dict[str, Any]] = []
        self._last_conversation_signature: tuple[str, str, str, tuple[str, ...]] | None = None
        self._recent_conversation_signatures: list[tuple[str, str, tuple[str, ...]]] = []
        self.arrival_stage_minutes = 6
        self.scene_runtime: dict[str, Any] = {
            "er_beds": {},
            "observation_beds": {},
            "await_slots": {},
            "specialty_consults": {},
            "discharge_slots": {},
            "waiting_seats": {},
            "doctor_pairings": {
                "er": "",
            },
            "specialty_calls": {},
            "patient_overrides": {},
            "doctor_overrides": {},
        }

    def initialize(self, queue: list[dict[str, Any]]) -> None:
        self.queue_items = [dict(item) for item in queue]
        self._assign_arrival_flow_overrides(current_time_min=0)
        self._assign_waiting_seats()
        self._write_snapshot(current_time_min=0, phase="initialized", actor="system", action="initialized")

    def on_case_selected(
        self,
        selected: dict[str, Any],
        remaining_queue: list[dict[str, Any]],
        *,
        selection_order: int,
        active_start_time_min: int,
        dynamic_priority: dict[str, Any],
    ) -> None:
        self.queue_items = [dict(item) for item in remaining_queue]
        case = dict(selected.get("case", {}) or {})
        case_id = str(case.get("case_id", "")).strip()
        self.current_payload[case_id] = {
            "selection_order": selection_order,
            "active_start_time_min": active_start_time_min,
            "dynamic_priority": dict(dynamic_priority or {}),
            "triage_level": int(selected.get("triage_level", 3) or 3),
            "arrival_time_min": int(selected.get("arrival_time_min", 0) or 0),
            "deterioration_risk": str(selected.get("deterioration_risk", "")).strip(),
        }
        patient_overrides = dict(self.scene_runtime.get("patient_overrides", {}) or {})
        doctor_overrides = dict(self.scene_runtime.get("doctor_overrides", {}) or {})
        patient_overrides[case_id] = "triage_queue_1"
        self.scene_runtime["patient_overrides"] = patient_overrides
        doctor_overrides["er"] = "triage_desk"
        self.scene_runtime["doctor_overrides"] = doctor_overrides
        self._assign_arrival_flow_overrides(current_time_min=active_start_time_min)
        self._assign_waiting_seats()
        self._write_snapshot(
            current_time_min=active_start_time_min,
            phase="case_selected",
            actor="system",
            action="case_selected",
        )

    def on_update(self, payload: dict[str, Any]) -> None:
        case_id = str(payload.get("case_id", "")).strip()
        if not case_id:
            return
        state = dict(payload.get("state", {}) or {})
        self.case_state_map[case_id] = {
            "case_id": case_id,
            "phase": str(payload.get("phase", "")).strip(),
            "actor": str(payload.get("actor", "")).strip(),
            "action": str(payload.get("action", "")).strip(),
            "target": str(payload.get("target", "")).strip(),
            "queue_context": dict(payload.get("queue_context", {}) or {}),
            "state": state,
            "transcript_tail": list(payload.get("transcript_tail", []) or []),
            "conversation_lines": [str(line).strip() for line in list(payload.get("conversation_lines", []) or []) if str(line).strip()],
        }
        current_time_min = int(state.get("current_time_min", 0) or 0)
        self._update_scene_runtime(
            case_id=case_id,
            item=self.case_state_map[case_id],
            current_time_min=current_time_min,
        )
        if str(payload.get("phase", "")).strip() == "case_completed":
            self.completed_case_ids.add(case_id)
        self._write_snapshot(
            current_time_min=current_time_min,
            phase=str(payload.get("phase", "")).strip(),
            actor=str(payload.get("actor", "")).strip(),
            action=str(payload.get("action", "")).strip(),
        )

    def finalize(self) -> None:
        last_time = max(
            [0]
            + [
                int((item.get("state", {}) or {}).get("current_time_min", 0) or 0)
                for item in self.case_state_map.values()
            ]
        )
        self._write_snapshot(current_time_min=last_time, phase="completed", actor="system", action="completed")
        self.history_path.write_text(json.dumps(self.history, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _is_conversation_text(text: str) -> bool:
        normalized = str(text).strip()
        if not normalized:
            return False
        lowered = normalized.lower()
        blocked_prefixes = (
            "hospital_coordinator:",
            "neurology_step:",
            "cardiology_step:",
            "pulmonology_step:",
            "gastroenterology_step:",
            "nephrology_step:",
            "hematology_step:",
            "infectious_disease_step:",
            "orthopedics_step:",
            "obstetrics_gynecology_step:",
            "urology_step:",
            "psychiatry_step:",
            "general_medicine_step:",
            "internal_medicine_step:",
            "surgery_step:",
            "er_department_step:",
            "triage:",
            "assessment:",
            "routing_review:",
            "ownership_review:",
            "diagnostic_service:",
            "accepting_service:",
            "handoff_summary:",
            "llm_debug:",
            "neurology_llm_debug:",
            "cardiology_llm_debug:",
            "pulmonology_llm_debug:",
            "gastroenterology_llm_debug:",
            "nephrology_llm_debug:",
            "hematology_llm_debug:",
            "infectious_disease_llm_debug:",
            "orthopedics_llm_debug:",
            "obstetrics_gynecology_llm_debug:",
            "urology_llm_debug:",
            "psychiatry_llm_debug:",
            "general_medicine_llm_debug:",
            "internal_medicine_llm_debug:",
            "surgery_llm_debug:",
        )
        if lowered.startswith(blocked_prefixes):
            return False
        if normalized.startswith("{") and normalized.endswith("}"):
            return False
        if "'action'" in normalized or '"action"' in normalized:
            return False
        if "'rationale'" in normalized or '"rationale"' in normalized:
            return False
        if "'used_llm'" in normalized or '"used_llm"' in normalized:
            return False
        return True

    @classmethod
    def _format_conversation_line(cls, role: str, content: str) -> str:
        normalized_role = str(role).strip().lower()
        text = str(content).strip()
        if not text:
            return ""
        if normalized_role in {"patient"}:
            return f"Patient: {text}"
        if normalized_role in {"er_interview", "er_doctor", "doctor"}:
            return f"ER: {text}"
        if normalized_role in {"specialty_interview", "specialist"}:
            return f"Specialist: {text}"
        return text

    @classmethod
    def _extract_conversation_lines(cls, transcript_tail: list[Any]) -> list[str]:
        lines: list[str] = []
        for line in list(transcript_tail or []):
            if isinstance(line, dict):
                role = str(line.get("role", "")).strip().lower()
                content = str(line.get("content", "")).strip()
                if role in {"system", "debug", "tool"}:
                    continue
                if cls._is_conversation_text(content):
                    formatted = cls._format_conversation_line(role, content)
                    if formatted:
                        lines.append(formatted)
                continue

            text = str(line).strip()
            if cls._is_conversation_text(text):
                lines.append(text)
        return lines

    @classmethod
    def _extract_trajectory_conversation_lines(cls, state: dict[str, Any]) -> list[str]:
        steps = list(state.get("trajectory_steps", []) or [])
        for step in reversed(steps):
            if str(step.get("action", "")).strip() != "ask_patient":
                continue
            outcome = dict(step.get("outcome", {}) or {})
            question = str(outcome.get("question", "")).strip()
            answer = str(outcome.get("answer", "")).strip()
            lines: list[str] = []
            if question and cls._is_conversation_text(question):
                lines.append(cls._format_conversation_line("er_interview", question))
            if answer and cls._is_conversation_text(answer):
                lines.append(cls._format_conversation_line("patient", answer))
            if lines:
                return lines
        return []

    def _conversation_lines_for_item(self, item: dict[str, Any]) -> list[str]:
        direct_lines = [str(line).strip() for line in list(item.get("conversation_lines", []) or []) if str(line).strip()]
        if direct_lines:
            return direct_lines
        state = dict(item.get("state", {}) or {})
        actor = str(item.get("actor", "")).strip()
        action = str(item.get("action", "")).strip()
        if actor == "er_department" and action == "ask_patient":
            trajectory_lines = self._extract_trajectory_conversation_lines(state)
            if trajectory_lines:
                return trajectory_lines
        if action != "ask_patient":
            return []
        transcript_tail = list(item.get("transcript_tail", []) or [])
        return self._extract_conversation_lines(transcript_tail)

    def _latest_dialogue_item(self) -> dict[str, Any] | None:
        candidates: list[tuple[int, int, int, dict[str, Any]]] = []
        for item in self.case_state_map.values():
            actor = str(item.get("actor", "")).strip()
            if actor in {"", "system"}:
                continue
            conversation_lines = self._conversation_lines_for_item(item)
            if not conversation_lines:
                continue
            state = dict(item.get("state", {}) or {})
            current_time = int(state.get("current_time_min", 0) or 0)
            has_direct = 1 if list(item.get("conversation_lines", []) or []) else 0
            er_tiebreak = 1 if actor == "er_department" else 0
            candidates.append((current_time, has_direct, er_tiebreak, item))

        if not candidates:
            return None
        candidates.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
        return candidates[0][3]

    def _dialogue_snapshot(self) -> dict[str, Any]:
        latest_item = self._latest_dialogue_item()

        if latest_item is None:
            return {
                "case_id": "",
                "actor": "",
                "action": "",
                "lines": [],
                "speaker_entity_id": "",
                "listener_entity_id": "",
                "bubble_text": "",
            }

        actor = str(latest_item.get("actor", "")).strip()
        case_id = str(latest_item.get("case_id", "")).strip()
        action = str(latest_item.get("action", "")).strip()
        lines = self._conversation_lines_for_item(latest_item)[-4:]
        bubble_text = lines[-1] if lines else ""

        speaker_entity_id = ""
        listener_entity_id = ""
        lowered_bubble = bubble_text.lower()
        if actor == "er_department":
            if lowered_bubble.startswith("patient:"):
                speaker_entity_id = f"patient_{case_id}" if case_id else ""
                listener_entity_id = "doctor_er_0"
            else:
                speaker_entity_id = "doctor_er_0"
                listener_entity_id = f"patient_{case_id}" if case_id else ""
        elif actor and actor not in {"system"}:
            if lowered_bubble.startswith("patient:"):
                speaker_entity_id = f"patient_{case_id}" if case_id else ""
                listener_entity_id = f"specialty_{actor}"
            else:
                speaker_entity_id = f"specialty_{actor}"
                listener_entity_id = f"patient_{case_id}" if case_id else ""

        return {
            "case_id": case_id,
            "actor": actor,
            "action": action,
            "lines": lines,
            "speaker_entity_id": speaker_entity_id,
            "listener_entity_id": listener_entity_id,
            "bubble_text": bubble_text.split(": ", 1)[-1][:72] if bubble_text else "",
        }

    def _remember_dialogue(self, dialogue: dict[str, Any], current_time_min: int) -> None:
        lines = [str(line).strip() for line in list(dialogue.get("lines", []) or []) if str(line).strip()]
        if not lines:
            return
        compact_signature = (
            str(dialogue.get("actor", "")).strip(),
            str(dialogue.get("case_id", "")).strip(),
            tuple(lines),
        )
        if compact_signature in self._recent_conversation_signatures:
            return
        signature = (
            str(dialogue.get("actor", "")).strip(),
            str(dialogue.get("case_id", "")).strip(),
            str(dialogue.get("action", "")).strip(),
            tuple(lines),
        )
        if signature == self._last_conversation_signature:
            return
        self._last_conversation_signature = signature
        self._recent_conversation_signatures.append(compact_signature)
        self._recent_conversation_signatures = self._recent_conversation_signatures[-24:]
        self.conversation_history.append(
            {
                "minute": int(current_time_min or 0),
                "actor": str(dialogue.get("actor", "")).strip(),
                "case_id": str(dialogue.get("case_id", "")).strip(),
                "action": str(dialogue.get("action", "")).strip(),
                "lines": lines,
            }
        )
        self.conversation_history = self.conversation_history[-12:]

    def _er_focus_snapshot(self) -> dict[str, Any]:
        latest_er_item: dict[str, Any] | None = None
        latest_time = -1
        for item in self.case_state_map.values():
            actor = str(item.get("actor", "")).strip()
            if actor != "er_department":
                continue
            state = dict(item.get("state", {}) or {})
            current_time = int(state.get("current_time_min", 0) or 0)
            if current_time >= latest_time:
                latest_time = current_time
                latest_er_item = item

        if latest_er_item is None:
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

        case_id = str(latest_er_item.get("case_id", "")).strip()
        state = dict(latest_er_item.get("state", {}) or {})
        queue_context = dict(latest_er_item.get("queue_context", {}) or {})
        dynamic = dict(queue_context.get("dynamic_priority", {}) or {})
        zone = self._classify_zone(case_id, latest_er_item)
        triage_level = int(queue_context.get("triage_level", state.get("triage_level", 3)) or state.get("triage_level", 3) or 3)
        effective_triage_level = int(dynamic.get("effective_triage_level", triage_level) or triage_level)
        return {
            "case_id": case_id,
            "action": str(latest_er_item.get("action", "")).strip(),
            "zone": zone,
            "triage_level": triage_level,
            "effective_triage_level": effective_triage_level,
            "deterioration_risk": str(
                queue_context.get("deterioration_risk", state.get("deterioration_risk", ""))
            ).strip(),
            "pending_results_count": len(list(state.get("pending_results", []) or [])),
            "observation_status": str(state.get("observation_status", "")).strip(),
            "working_diagnosis": str(state.get("er_working_diagnosis", "")).strip(),
            "responsible_department": str(state.get("responsible_department", "")).strip(),
        }

    def _classify_zone(self, case_id: str, item: dict[str, Any]) -> str:
        if case_id in self.completed_case_ids:
            return "completed"

        state = dict(item.get("state", {}) or {})
        actor = str(item.get("actor", "")).strip()
        action = str(item.get("action", "")).strip()
        observation_status = str(state.get("observation_status", "")).strip().lower()
        pending_results = list(state.get("pending_results", []) or [])

        if observation_status in {"under_observation", "reassessment_due"} or action == "observe_patient":
            return "observation"
        if pending_results:
            return "awaiting_results"
        if actor and actor not in {"system", "er_department"}:
            return "specialty_review"
        return "er_workup"

    def _zone_slots(self, zone_key: str) -> list[str]:
        zone_slots = dict(self.layout.get("zone_slots", {}) or {})
        return [str(value).strip() for value in list(zone_slots.get(zone_key, []) or []) if str(value).strip()]

    @staticmethod
    def _free_slot(slot_map: dict[str, str], slots: list[str], case_id: str) -> str:
        for slot_id, assigned_case_id in slot_map.items():
            if assigned_case_id == case_id:
                return slot_id
        used = set(slot_map.keys())
        for slot_id in slots:
            if slot_id not in used:
                return slot_id
        return slots[-1] if slots else ""

    def _release_case_assignments(self, case_id: str, keep_keys: set[str] | None = None) -> None:
        keep_keys = keep_keys or set()
        for key in ("er_beds", "observation_beds", "await_slots", "specialty_consults", "discharge_slots"):
            if key in keep_keys:
                continue
            slot_map = dict(self.scene_runtime.get(key, {}) or {})
            self.scene_runtime[key] = {
                slot_id: assigned_case_id
                for slot_id, assigned_case_id in slot_map.items()
                if assigned_case_id != case_id
            }

    def _assign_arrival_flow_overrides(self, *, current_time_min: int) -> None:
        patient_overrides = dict(self.scene_runtime.get("patient_overrides", {}) or {})
        for case_id, location_id in list(patient_overrides.items()):
            if str(location_id).startswith("arrival_lane_") or str(location_id).startswith("arrival_entry_"):
                patient_overrides.pop(case_id, None)

        arrival_slots = (
            ("arrival_entry_1", "arrival_lane_1"),
            ("arrival_entry_2", "arrival_lane_2"),
            ("arrival_entry_3", "arrival_lane_3"),
        )
        slot_index = 0
        for item in self.queue_items:
            if slot_index >= len(arrival_slots):
                break
            case = dict(item.get("case", {}) or {})
            case_id = str(case.get("case_id", "")).strip()
            arrival_time_min = int(item.get("arrival_time_min", 0) or 0)
            if not case_id:
                continue
            if case_id in self.case_state_map:
                continue
            elapsed = current_time_min - arrival_time_min
            if 0 <= elapsed < self.arrival_stage_minutes:
                entry_slot, lane_slot = arrival_slots[slot_index]
                patient_overrides[case_id] = entry_slot if elapsed < 2 else lane_slot
                slot_index += 1

        self.scene_runtime["patient_overrides"] = patient_overrides

    def _assign_waiting_seats(self) -> None:
        slots = self._zone_slots("waiting_room")
        seat_map: dict[str, str] = {}
        arrival_override_cases = {
            case_id
            for case_id, location_id in dict(self.scene_runtime.get("patient_overrides", {}) or {}).items()
            if str(location_id).startswith("arrival_lane_") or str(location_id).startswith("arrival_entry_")
        }
        seat_index = 0
        for item in self.queue_items:
            case = dict(item.get("case", {}) or {})
            case_id = str(case.get("case_id", "")).strip()
            if not case_id:
                continue
            if case_id in arrival_override_cases:
                continue
            slot_id = slots[seat_index] if seat_index < len(slots) else (slots[-1] if slots else "")
            if slot_id:
                seat_map[slot_id] = case_id
                seat_index += 1
        self.scene_runtime["waiting_seats"] = seat_map

    def _schedule_specialty_call(self, department: str, case_id: str, current_time_min: int) -> None:
        normalized = str(department).strip()
        if not normalized:
            return
        calls = dict(self.scene_runtime.get("specialty_calls", {}) or {})
        existing = dict(calls.get(normalized, {}) or {})
        arrival_min = int(existing.get("arrival_min", current_time_min + 5) or current_time_min + 5)
        calls[normalized] = {
            "status": "summoned",
            "case_id": case_id,
            "summoned_min": current_time_min,
            "arrival_min": arrival_min if arrival_min >= current_time_min else current_time_min + 5,
        }
        self.scene_runtime["specialty_calls"] = calls

    def _update_scene_runtime(self, *, case_id: str, item: dict[str, Any], current_time_min: int) -> None:
        state = dict(item.get("state", {}) or {})
        actor = str(item.get("actor", "")).strip()
        action = str(item.get("action", "")).strip()
        zone = self._classify_zone(case_id, item)
        patient_overrides = dict(self.scene_runtime.get("patient_overrides", {}) or {})
        doctor_overrides = dict(self.scene_runtime.get("doctor_overrides", {}) or {})

        if actor == "er_department" and action == "make_diagnostic_summary":
            department = str(state.get("responsible_department", "")).strip()
            self._schedule_specialty_call(department, case_id, current_time_min)

        if actor == "er_department" and action == "perform_triage":
            patient_overrides[case_id] = "triage_desk"
            doctor_overrides["er"] = "triage_desk"
        elif actor == "er_department" and action in {"perform_assessment", "ask_patient", "request_test", "await_test_results", "make_diagnostic_summary", "observe_patient", "stabilize"}:
            patient_overrides.pop(case_id, None)
            doctor_overrides.pop("er", None)

        if zone == "er_workup":
            self._release_case_assignments(case_id, keep_keys={"er_beds"})
            slots = self._zone_slots("er_workup")
            bed_map = dict(self.scene_runtime.get("er_beds", {}) or {})
            slot_id = self._free_slot(bed_map, slots, case_id)
            if slot_id:
                bed_map[slot_id] = case_id
                self.scene_runtime["er_beds"] = bed_map
            if actor == "er_department":
                self.scene_runtime["doctor_pairings"]["er"] = case_id
        elif zone == "observation":
            patient_overrides.pop(case_id, None)
            self._release_case_assignments(case_id, keep_keys={"observation_beds"})
            slots = self._zone_slots("observation")
            bed_map = dict(self.scene_runtime.get("observation_beds", {}) or {})
            slot_id = self._free_slot(bed_map, slots, case_id)
            if slot_id:
                bed_map[slot_id] = case_id
                self.scene_runtime["observation_beds"] = bed_map
            if actor == "er_department":
                self.scene_runtime["doctor_pairings"]["er"] = case_id
        elif zone == "awaiting_results":
            patient_overrides.pop(case_id, None)
            self._release_case_assignments(case_id, keep_keys={"await_slots"})
            slots = self._zone_slots("awaiting_results")
            wait_map = dict(self.scene_runtime.get("await_slots", {}) or {})
            slot_id = self._free_slot(wait_map, slots, case_id)
            if slot_id:
                wait_map[slot_id] = case_id
                self.scene_runtime["await_slots"] = wait_map
        elif zone == "specialty_review":
            patient_overrides.pop(case_id, None)
            self._release_case_assignments(case_id, keep_keys={"specialty_consults"})
            slots = self._zone_slots("specialty_review")
            consult_map = dict(self.scene_runtime.get("specialty_consults", {}) or {})
            slot_id = self._free_slot(consult_map, slots, case_id)
            if slot_id:
                consult_map[slot_id] = case_id
                self.scene_runtime["specialty_consults"] = consult_map
            if actor and actor not in {"system", "er_department"}:
                calls = dict(self.scene_runtime.get("specialty_calls", {}) or {})
                calls[actor] = {
                    "status": "consulting",
                    "case_id": case_id,
                    "summoned_min": int(calls.get(actor, {}).get("summoned_min", current_time_min) or current_time_min),
                    "arrival_min": int(calls.get(actor, {}).get("arrival_min", current_time_min) or current_time_min),
                }
                self.scene_runtime["specialty_calls"] = calls
        elif zone == "completed":
            patient_overrides.pop(case_id, None)
            self._release_case_assignments(case_id, keep_keys={"discharge_slots"})
            slots = self._zone_slots("completed")
            discharge_map = dict(self.scene_runtime.get("discharge_slots", {}) or {})
            slot_id = self._free_slot(discharge_map, slots, case_id)
            if slot_id:
                discharge_map[slot_id] = case_id
                self.scene_runtime["discharge_slots"] = discharge_map

        # Clear ER pairing if the paired case has left active ER work.
        if self.scene_runtime.get("doctor_pairings", {}).get("er") == case_id and zone not in {"er_workup", "observation"}:
            self.scene_runtime["doctor_pairings"]["er"] = ""
            doctor_overrides.pop("er", None)

        # Update waiting seats after queue changes and state changes.
        self.scene_runtime["patient_overrides"] = patient_overrides
        self.scene_runtime["doctor_overrides"] = doctor_overrides
        self._assign_arrival_flow_overrides(current_time_min=current_time_min)
        self._assign_waiting_seats()

    def _patient_alerts(self, state: dict[str, Any]) -> list[str]:
        alerts: list[str] = []
        if list(state.get("pending_results", []) or []):
            alerts.append("pending_result")
        if list(state.get("deterioration_events", []) or []):
            alerts.append("deterioration")
        if str(state.get("observation_status", "")).strip().lower() in {"under_observation", "reassessment_due", "completed"}:
            alerts.append("observation")
        if int((state.get("queue_metrics", {}) or {}).get("wait_escalation_steps", 0) or 0) > 0:
            alerts.append("reprioritized")
        return alerts

    def _waiting_patients(self) -> list[dict[str, Any]]:
        waiting: list[dict[str, Any]] = []
        for item in self.queue_items:
            case = dict(item.get("case", {}) or {})
            case_id = str(case.get("case_id", "")).strip()
            if not case_id:
                continue
            dynamic = dict(item.get("dynamic_priority", {}) or {})
            waiting.append(
                {
                    "case_id": case_id,
                    "zone": "waiting_room",
                    "triage_level": int(item.get("triage_level", 3) or 3),
                    "effective_triage_level": int(dynamic.get("effective_triage_level", item.get("triage_level", 3)) or item.get("triage_level", 3) or 3),
                    "predicted_diagnosis": "",
                    "predicted_department": "",
                    "alerts": [],
                }
            )
        return waiting

    def _resource_occupancy(self, current_time_min: int) -> list[dict[str, Any]]:
        occupancy: list[dict[str, Any]] = []
        for item in self.case_state_map.values():
            state = dict(item.get("state", {}) or {})
            case_id = str(item.get("case_id", "")).strip()
            for event in list(state.get("resource_events", []) or []):
                start = int(event.get("actual_start_min", 0) or 0)
                end = int(event.get("end_time_min", 0) or 0)
                if start <= current_time_min < end:
                    occupancy.append(
                        {
                            "case_id": case_id,
                            "resource_kind": str(event.get("resource_kind", "")).strip(),
                            "action": str(event.get("action", "")).strip(),
                            "target": str(event.get("target", "")).strip(),
                            "start_time_min": start,
                            "end_time_min": end,
                        }
                    )
        return occupancy

    @staticmethod
    def _recent_case_events(state: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for event in list(state.get("event_log", []) or []):
            event_dict = dict(event or {})
            if not event_dict:
                continue
            state_delta = dict(event_dict.get("state_delta", {}) or {})
            events.append(
                {
                    "event_id": str(event_dict.get("event_id", "")).strip(),
                    "run_id": str(event_dict.get("run_id", "")).strip(),
                    "minute": int(event_dict.get("minute", 0) or 0),
                    "tick": int(event_dict.get("tick", 0) or 0),
                    "phase": str(event_dict.get("phase", "")).strip(),
                    "event_type": str(event_dict.get("event_type", "")).strip(),
                    "action": str(event_dict.get("action", "")).strip(),
                    "location_id": str(event_dict.get("location_id", "")).strip(),
                    "resource_kind": str(event_dict.get("resource_kind", "")).strip(),
                    "rationale": str(event_dict.get("rationale", "")).strip(),
                    "payload": dict(event_dict.get("payload", {}) or {}),
                    "state_delta": state_delta,
                    "zone": str(event_dict.get("zone", "")).strip() or str(state_delta.get("zone", "")).strip(),
                    "meta": dict(event_dict.get("meta", {}) or {}),
                    "actor": dict(event_dict.get("actor", {}) or {}),
                    "target": dict(event_dict.get("target", {}) or {}),
                }
            )
        return events[-limit:]

    @staticmethod
    def _case_questions(state: dict[str, Any]) -> list[dict[str, str]]:
        questions: list[dict[str, str]] = []
        for step in list(state.get("trajectory_steps", []) or []):
            if str(step.get("action", "")).strip() != "ask_patient":
                continue
            outcome = dict(step.get("outcome", {}) or {})
            question = str(outcome.get("question", "")).strip()
            answer = str(outcome.get("answer", "")).strip()
            if question or answer:
                questions.append({"question": question, "answer": answer})
        return questions[-4:]

    @staticmethod
    def _case_tests(state: dict[str, Any]) -> list[str]:
        tests: list[str] = []
        for step in list(state.get("trajectory_steps", []) or []):
            if str(step.get("action", "")).strip() != "request_test":
                continue
            outcome = dict(step.get("outcome", {}) or {})
            requested = str(outcome.get("requested_test", "")).strip()
            resolved = str(outcome.get("resolved_name", "")).strip()
            ready_time = outcome.get("ready_time_min")
            if requested or resolved:
                label = resolved or requested
                if ready_time not in (None, ""):
                    label = f"{label} (ready m{int(ready_time or 0)})"
                tests.append(label)
        return tests[-6:]

    @staticmethod
    def _case_decision_points(state: dict[str, Any]) -> list[dict[str, Any]]:
        decision_points: list[dict[str, Any]] = []
        for snapshot in list(state.get("decision_snapshots", []) or []):
            snapshot_dict = dict(snapshot or {})
            proposed = dict(snapshot_dict.get("proposed_action", {}) or {})
            alternatives = list(snapshot_dict.get("alternatives", []) or [])
            decision_points.append(
                {
                    "snapshot_id": str(snapshot_dict.get("snapshot_id", "")).strip(),
                    "node": str(snapshot_dict.get("node", "")).strip(),
                    "turn_index": int(snapshot_dict.get("turn_index", 0) or 0),
                    "proposed_type": str(proposed.get("type", "")).strip(),
                    "proposed_target": str(proposed.get("target", "")).strip(),
                    "alternatives_count": len(alternatives),
                    "alternatives": [
                        {
                            "type": str(dict(option).get("type", "")).strip(),
                            "target": str(dict(option).get("target", "")).strip(),
                            "rationale": str(dict(option).get("rationale", "")).strip(),
                        }
                        for option in alternatives[:5]
                    ],
                }
            )
        return decision_points[-4:]

    @staticmethod
    def _case_detail(case_id: str, patient: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
        state = dict(item.get("state", {}) or {})
        queue_context = dict(item.get("queue_context", {}) or {})
        dynamic = dict(queue_context.get("dynamic_priority", {}) or {})
        return {
            "case_id": case_id,
            "zone": str(patient.get("zone", "")).strip(),
            "triage_level": int(patient.get("triage_level", 3) or 3),
            "effective_triage_level": int(patient.get("effective_triage_level", 3) or 3),
            "deterioration_risk": str(
                queue_context.get("deterioration_risk", state.get("deterioration_risk", ""))
            ).strip(),
            "predicted_department": str(patient.get("predicted_department", "")).strip(),
            "predicted_diagnosis": str(patient.get("predicted_diagnosis", "")).strip(),
            "pending_results_count": len(list(state.get("pending_results", []) or [])),
            "objective_findings": [str(line).strip() for line in list(state.get("objective_findings", []) or []) if str(line).strip()][-6:],
            "questions": LiveVisualRuntimeWriter._case_questions(state),
            "tests": LiveVisualRuntimeWriter._case_tests(state),
            "decision_points": LiveVisualRuntimeWriter._case_decision_points(state),
            "counterfactual_candidates": list(state.get("counterfactual_action_candidates", []) or [])[:5],
            "what_if_stats": dict(state.get("what_if_stats", {}) or {}),
            "wait_escalation_steps": int(dynamic.get("wait_escalation_steps", 0) or 0),
            "alerts": list(patient.get("alerts", []) or []),
            "recent_events": LiveVisualRuntimeWriter._recent_case_events(state, limit=8),
        }

    def _event_log_recent(self, limit: int = 40) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for item in self.case_state_map.values():
            state = dict(item.get("state", {}) or {})
            events.extend(self._recent_case_events(state, limit=limit))
        events.sort(key=lambda event: (int(event.get("minute", 0) or 0), int(event.get("tick", 0) or 0), str(event.get("event_id", ""))))
        return events[-limit:]

    def _conversation_log_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for entry in list(self.conversation_history or [])[-limit:]:
            entries.append(
                {
                    "minute": int(entry.get("minute", 0) or 0),
                    "actor": str(entry.get("actor", "")).strip(),
                    "case_id": str(entry.get("case_id", "")).strip(),
                    "action": str(entry.get("action", "")).strip(),
                    "lines": [str(line).strip() for line in list(entry.get("lines", []) or []) if str(line).strip()],
                }
            )
        return entries[-limit:]

    def _world_snapshot(
        self,
        *,
        current_time_min: int,
        patients: list[dict[str, Any]],
        resource_occupancy: list[dict[str, Any]],
        case_details: dict[str, Any],
        scene_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        scene = dict(scene_snapshot or {})
        entities = list(scene.get("entities", []) or [])
        zone_slots = dict(self.layout.get("zone_slots", {}) or {})
        rooms: list[dict[str, Any]] = []
        for zone_name, slots in zone_slots.items():
            occupants = [
                str(patient.get("case_id", "")).strip()
                for patient in patients
                if str(patient.get("movement_target_id", "")).strip() in {str(slot).strip() for slot in list(slots or [])}
                or str(patient.get("zone", "")).strip() == str(zone_name).strip()
            ]
            rooms.append(
                {
                    "room_id": str(zone_name).strip(),
                    "room_type": str(zone_name).strip(),
                    "activity_label": str(zone_name).replace("_", " ").strip(),
                    "occupants": occupants,
                    "active_case_ids": occupants,
                }
            )
        queues = [
            {
                "queue_id": "waiting_room",
                "case_ids": [str(patient.get("case_id", "")).strip() for patient in patients if str(patient.get("zone", "")).strip() == "waiting_room"],
                "priority_mode": self.queue_policy,
                "last_updated_minute": int(current_time_min or 0),
            },
            {
                "queue_id": "pending_results",
                "case_ids": [case_id for case_id, detail in case_details.items() if int(dict(detail).get("pending_results_count", 0) or 0) > 0],
                "priority_mode": "temporal",
                "last_updated_minute": int(current_time_min or 0),
            },
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
                    "current_location_id": str(patient.get("movement_target_id", "")).strip(),
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
            "actors": entities,
            "rooms": rooms,
            "resources": list(resource_occupancy),
            "queues": queues,
            "cases": cases,
        }

    def _build_case_details(self, patients: list[dict[str, Any]]) -> dict[str, Any]:
        details: dict[str, Any] = {}
        patient_by_case = {str(patient.get("case_id", "")).strip(): patient for patient in patients}
        for case_id, item in self.case_state_map.items():
            patient = dict(patient_by_case.get(case_id, {}) or {})
            if not patient:
                continue
            details[case_id] = self._case_detail(case_id, patient, item)
        for patient in patients:
            case_id = str(patient.get("case_id", "")).strip()
            if not case_id or case_id in details:
                continue
            details[case_id] = {
                "case_id": case_id,
                "zone": str(patient.get("zone", "")).strip(),
                "triage_level": int(patient.get("triage_level", 3) or 3),
                "effective_triage_level": int(patient.get("effective_triage_level", 3) or 3),
                "deterioration_risk": "",
                "predicted_department": str(patient.get("predicted_department", "")).strip(),
                "predicted_diagnosis": str(patient.get("predicted_diagnosis", "")).strip(),
                "pending_results_count": 0,
                "objective_findings": [],
                "questions": [],
                "tests": [],
                "decision_points": [],
                "counterfactual_candidates": [],
                "what_if_stats": {},
                "wait_escalation_steps": 0,
                "alerts": list(patient.get("alerts", []) or []),
            }
        return details

    def _write_snapshot(self, *, current_time_min: int, phase: str, actor: str, action: str) -> None:
        patients = self._waiting_patients()
        for case_id, item in self.case_state_map.items():
            state = dict(item.get("state", {}) or {})
            queue_context = dict(item.get("queue_context", {}) or {})
            zone = self._classify_zone(case_id, item)
            dynamic = dict(queue_context.get("dynamic_priority", {}) or {})
            assigned_staff = ""
            if self.scene_runtime.get("doctor_pairings", {}).get("er") == case_id:
                assigned_staff = "doctor_er_0"
            elif zone == "specialty_review":
                for department, call in dict(self.scene_runtime.get("specialty_calls", {}) or {}).items():
                    call_dict = dict(call or {})
                    if (
                        str(call_dict.get("case_id", "")).strip() == case_id
                        and str(call_dict.get("status", "")).strip().lower() == "consulting"
                    ):
                        assigned_staff = f"specialty_{department}"
                        break
            patients.append(
                {
                    "case_id": case_id,
                    "zone": zone,
                    "triage_level": int(queue_context.get("triage_level", state.get("triage_level", 3)) or state.get("triage_level", 3) or 3),
                    "effective_triage_level": int(dynamic.get("effective_triage_level", queue_context.get("triage_level", state.get("triage_level", 3))) or queue_context.get("triage_level", state.get("triage_level", 3)) or 3),
                    "predicted_diagnosis": str(state.get("final_diagnosis", "") or state.get("er_working_diagnosis", "")).strip(),
                    "predicted_department": str(state.get("final_department", "") or state.get("responsible_department", "")).strip(),
                    "alerts": self._patient_alerts(state),
                    "last_action": str(item.get("action", "")).strip(),
                    "actor": str(item.get("actor", "")).strip(),
                    "assigned_staff": assigned_staff,
                    "movement_target_id": _assigned_slot_name(self.scene_runtime, case_id),
                }
            )

        zones = {
            zone: [patient for patient in patients if patient["zone"] == zone]
            for zone in ZONE_ORDER
        }
        dialogue = self._dialogue_snapshot()
        self._remember_dialogue(dialogue, current_time_min)
        resource_occupancy = self._resource_occupancy(current_time_min)
        case_details = self._build_case_details(patients)
        scene_snapshot = build_hospital_scene_snapshot(
            patients=patients,
            case_state_map=self.case_state_map,
            runtime_scene_state=self.scene_runtime,
            current_time_min=current_time_min,
        )
        snapshot = {
            "run_id": self.run_id,
            "queue_policy": self.queue_policy,
            "current_time_min": current_time_min,
            "snapshot_written_at_unix": time.time(),
            "phase": phase,
            "actor": actor,
            "action": action,
            "simulation_status": "completed" if phase == "completed" else "running",
            "zones": zones,
            "patients": patients,
            "resource_occupancy": resource_occupancy,
            "completed_count": len(self.completed_case_ids),
            "waiting_count": len(zones.get("waiting_room", [])),
            "dialogue": dialogue,
            "conversation_history": list(self.conversation_history),
            "conversation_log_recent": self._conversation_log_recent(),
            "event_log_recent": self._event_log_recent(),
            "er_focus": self._er_focus_snapshot(),
            "case_details": case_details,
        }
        snapshot["scene"] = scene_snapshot
        snapshot["world"] = self._world_snapshot(
            current_time_min=current_time_min,
            patients=patients,
            resource_occupancy=resource_occupancy,
            case_details=case_details,
            scene_snapshot=scene_snapshot,
        )
        self.snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        self.history.append(snapshot)
        if self.step_delay_sec > 0 and phase not in {"initialized", "completed"}:
            time.sleep(self.step_delay_sec)
