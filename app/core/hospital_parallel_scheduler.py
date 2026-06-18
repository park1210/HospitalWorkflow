from __future__ import annotations

from typing import Any

from app.core.event_schema import make_clinical_event
from app.core.hospital_case_runtime import HospitalCaseRuntime
from app.core.hospital_clinical_policy import HospitalClinicalPolicy
from app.core.hospital_resource_registry import HospitalResource
from app.core.hospital_route_graph import normalize_movement_path, route_distance
from app.core.hospital_scheduler_state import HospitalSchedulerState
from app.core.hospital_specialty_policy import HospitalSpecialtyPolicy
from app.core.queue_manager import QueueManager
from app.utils.department_catalog import normalize_department


def _bedside_location_for_runtime(runtime: HospitalCaseRuntime) -> str:
    bed_id = str(getattr(runtime, "assigned_bed_id", "")).strip()
    if bed_id.startswith("er_bed_"):
        return bed_id.replace("er_bed_", "er_bedside_")
    return bed_id or "er_bedside_1"


class HospitalParallelScheduler:
    def __init__(self) -> None:
        self.queue_manager = QueueManager()
        self.clinical_policy = HospitalClinicalPolicy()
        self.specialty_policy = HospitalSpecialtyPolicy()

    def initialize(self, cases: list[dict[str, Any]], run_id: str = "") -> HospitalSchedulerState:
        queued = self.queue_manager.build_priority_queue(cases)
        state = HospitalSchedulerState(run_id=str(run_id).strip())
        for item in queued:
            case = dict(item.get("case", {}) or {})
            case_id = str(case.get("case_id", "")).strip()
            if not case_id:
                continue
            runtime = HospitalCaseRuntime(
                case_id=case_id,
                case_data=case,
                arrival_time_min=int(item.get("arrival_time_min", 0) or 0),
                arrival_index=int(item.get("arrival_index", 0) or 0),
                triage_level=int(item.get("triage_level", 3) or 3),
                triage_rationale=str(item.get("triage_rationale", "")).strip(),
                deterioration_risk=str(item.get("deterioration_risk", "")).strip() or "low",
                effective_priority=int(item.get("triage_level", 3) or 3),
            )
            state.cases[case_id] = runtime
            state.arrival_queue.append(case_id)
        return state

    def step(self, state: HospitalSchedulerState) -> HospitalSchedulerState:
        self._process_scheduled_events(state)
        self._admit_arrivals(state)
        self._assign_triage(state)
        self._assign_beds(state)
        self._refresh_er_priorities(state)
        self._assign_er_work(state)
        self._start_requested_tests(state)
        self._assign_specialty_work(state)
        self._release_completed_resource_windows(state)
        state.tick += 1
        state.current_minute += 1
        return state

    def run_until(self, state: HospitalSchedulerState, minute_limit: int) -> HospitalSchedulerState:
        while int(state.current_minute or 0) < int(minute_limit or 0):
            self.step(state)
            if not state.active_case_ids():
                break
        return state

    def apply_branch_action(
        self,
        state: HospitalSchedulerState,
        *,
        case_id: str,
        selected_action: dict[str, Any],
    ) -> None:
        runtime = state.case(case_id)
        action_type = str(selected_action.get("type", "")).strip()
        target = str(selected_action.get("target", "")).strip()

        if action_type == "ask_patient":
            question = target or "Can you describe what feels most different right now?"
            answer = "The patient gives one more focused clarification without materially changing the existing story."
            runtime.question_history.append(
                {
                    "question": question,
                    "answer": answer,
                    "actor": runtime.assigned_er_doctor_id or "doctor_er_0",
                }
            )
            runtime.workflow_state = "waiting_er"
            runtime.zone = "er_workup"
            runtime.latest_action = "ask_history"
            runtime.latest_target = question
            runtime.latest_rationale = "The replay branch inserts one more targeted ER question before further escalation."
            state.er_queue = self._ensure_unique_queue(state.er_queue, case_id)
            self._record_event(
                state,
                case_id=case_id,
                action="ask_history",
                zone=runtime.zone,
                actor=runtime.assigned_er_doctor_id or "doctor_er_0",
                rationale=runtime.latest_rationale,
                event_type="question_asked",
                location_id=str(runtime.assigned_bed_id).strip() or "er_bed_1",
                payload={"question": question, "answer": answer},
            )
            return

        if action_type == "request_test":
            if target and target not in runtime.recommended_tests and target not in runtime.completed_tests:
                runtime.recommended_tests.append(target)
            runtime.workflow_state = "waiting_test"
            runtime.zone = "er_workup"
            runtime.latest_action = "order_test"
            runtime.latest_target = target
            runtime.latest_rationale = "The replay branch orders another targeted objective test before final disposition."
            state.test_queue = self._ensure_unique_queue(state.test_queue, case_id)
            state.er_queue = [item for item in list(state.er_queue or []) if str(item).strip() != str(case_id).strip()]
            self._record_event(
                state,
                case_id=case_id,
                action="order_test",
                zone=runtime.zone,
                actor=runtime.assigned_er_doctor_id or "doctor_er_0",
                rationale=runtime.latest_rationale,
                event_type="test_ordered",
                location_id=str(runtime.assigned_bed_id).strip() or "er_bed_1",
                payload={"requested_test": target},
            )
            return

        if action_type == "await_results":
            waiting_for = target or str(dict(runtime.pending_results[0] or {}).get("test_name", "")).strip()
            runtime.workflow_state = "waiting_test" if list(runtime.pending_results or []) else "waiting_er"
            runtime.zone = "awaiting_results" if list(runtime.pending_results or []) else "er_workup"
            runtime.latest_action = "await_results"
            runtime.latest_target = waiting_for
            runtime.latest_rationale = "The replay branch delays escalation and waits for the pending objective result first."
            state.er_queue = [item for item in list(state.er_queue or []) if str(item).strip() != str(case_id).strip()]
            self._record_event(
                state,
                case_id=case_id,
                action="await_results",
                zone=runtime.zone,
                actor=runtime.assigned_er_doctor_id or "doctor_er_0",
                rationale=runtime.latest_rationale,
                event_type="awaiting_results",
                location_id=str(runtime.assigned_bed_id).strip() or "er_bed_1",
                payload={"requested_test": waiting_for},
            )
            return

        if action_type in {"consult_specialty", "request_consult"}:
            if target:
                runtime.target_department = target
            runtime.workflow_state = "waiting_specialty"
            runtime.zone = "er_workup"
            runtime.latest_action = "request_specialty"
            runtime.latest_target = runtime.target_department
            runtime.latest_rationale = "The replay branch escalates directly to specialty ownership."
            state.specialty_queue = self._ensure_unique_queue(state.specialty_queue, case_id)
            state.er_queue = [item for item in list(state.er_queue or []) if str(item).strip() != str(case_id).strip()]
            self._record_event(
                state,
                case_id=case_id,
                action="request_specialty",
                zone=runtime.zone,
                actor=runtime.assigned_er_doctor_id or "doctor_er_0",
                rationale=runtime.latest_rationale,
                event_type="consult_requested",
                location_id=str(runtime.assigned_bed_id).strip() or "er_bed_1",
                payload={"department": runtime.target_department},
            )
            return

        if action_type == "diagnose":
            runtime.latest_action = "er_finalize"
            runtime.latest_target = target or str(runtime.assessment_summary).strip()
            runtime.latest_rationale = "The replay branch finalizes immediately from the current ER evidence."
            self._complete_case_from_er(state, runtime)

    def run_branch_until_stable(
        self,
        state: HospitalSchedulerState,
        *,
        case_id: str,
        minute_horizon: int = 12,
    ) -> HospitalSchedulerState:
        normalized_case_id = str(case_id).strip()
        for _ in range(max(1, int(minute_horizon or 0))):
            runtime = state.case(normalized_case_id)
            if runtime.is_completed:
                break
            previous_tick = int(state.tick or 0)
            self.step(state)
            runtime = state.case(normalized_case_id)
            is_waiting_stable = (
                str(runtime.workflow_state).strip() in {"waiting_er", "awaiting_results", "waiting_specialty", "completed"}
                and int(state.tick or 0) > previous_tick
            )
            if is_waiting_stable and not any(
                str(dict(event or {}).get("case_id", "")).strip() == normalized_case_id
                for event in list(state.scheduled_events or [])
            ):
                break
        return state

    @staticmethod
    def _set_runtime_movement(
        runtime: HospitalCaseRuntime,
        *,
        current_location_id: str = "",
        target_location_id: str = "",
        interaction_location_id: str = "",
        movement_path: list[str] | None = None,
        pending_interaction: dict[str, Any] | None = None,
    ) -> None:
        if current_location_id:
            runtime.current_location_id = str(current_location_id).strip()
        if target_location_id:
            runtime.target_location_id = str(target_location_id).strip()
        if interaction_location_id or interaction_location_id == "":
            runtime.interaction_location_id = str(interaction_location_id).strip()
        if movement_path is not None:
            runtime.movement_path = normalize_movement_path(
                [str(item).strip() for item in list(movement_path or []) if str(item).strip()],
                current_location_id=str(runtime.current_location_id).strip() or str(current_location_id).strip(),
                target_location_id=str(runtime.target_location_id).strip() or str(target_location_id).strip(),
            )
        if pending_interaction is not None:
            runtime.pending_interaction = dict(pending_interaction or {})

    @staticmethod
    def _wait_location_for_resource_type(resource_type: str) -> str:
        return "imaging_wait_1" if str(resource_type).strip() == "imaging_slot" else "lab_wait_1"

    @staticmethod
    def _state_delta(runtime: HospitalCaseRuntime) -> dict[str, Any]:
        return {
            "zone": str(runtime.zone).strip(),
            "workflow_state": str(runtime.workflow_state).strip(),
            "triage_level": int(runtime.triage_level or 3),
            "effective_priority": int(runtime.effective_priority or runtime.triage_level or 3),
            "pending_results_count": len(list(runtime.pending_results or [])),
            "target_department": str(runtime.target_department).strip(),
            "assigned_bed_id": str(runtime.assigned_bed_id).strip(),
            "assigned_er_doctor_id": str(runtime.assigned_er_doctor_id).strip(),
            "assigned_specialist_id": str(runtime.assigned_specialist_id).strip(),
            "er_arrival_min": int(runtime.er_arrival_min or 0),
            "er_started_min": int(runtime.er_started_min or 0),
            "specialty_arrival_min": int(runtime.specialty_arrival_min or 0),
            "specialty_started_min": int(runtime.specialty_started_min or 0),
            "current_location_id": str(runtime.current_location_id).strip(),
            "target_location_id": str(runtime.target_location_id).strip(),
            "interaction_location_id": str(runtime.interaction_location_id).strip(),
            "pending_interaction": dict(runtime.pending_interaction or {}),
        }

    @staticmethod
    def _resource_kind(actor: str) -> str:
        normalized = str(actor).strip().lower()
        if normalized.startswith("doctor_er"):
            return "er_doctor"
        if normalized.startswith("nurse_triage"):
            return "triage_nurse"
        if normalized.startswith("lab_slot"):
            return "lab_slot"
        if normalized.startswith("imaging_slot"):
            return "imaging_slot"
        if normalized.startswith("specialty_"):
            return "specialist"
        if normalized.startswith("consult_room"):
            return "consult_room"
        return "system"

    @staticmethod
    def _default_location_id(runtime: HospitalCaseRuntime, actor: str) -> str:
        normalized_actor = str(actor).strip().lower()
        if normalized_actor.startswith("nurse_triage"):
            return "triage_desk"
        if normalized_actor.startswith("doctor_er"):
            return "er_doctor_station"
        if normalized_actor.startswith("lab_slot"):
            return "lab_station"
        if normalized_actor.startswith("imaging_slot"):
            return "imaging_machine"
        if normalized_actor.startswith("specialty_"):
            return str(runtime.assigned_consult_room_id).strip() or "specialty_consult_1"
        return str(runtime.assigned_bed_id).strip() or str(runtime.assigned_consult_room_id).strip() or ""

    def _record_event(
        self,
        state: HospitalSchedulerState,
        *,
        case_id: str,
        action: str,
        zone: str,
        actor: str,
        rationale: str,
        event_type: str = "",
        location_id: str = "",
        payload: dict[str, Any] | None = None,
        target: dict[str, Any] | None = None,
    ) -> None:
        runtime = state.case(case_id)
        normalized_actor = str(actor).strip()
        actor_role = self._resource_kind(normalized_actor)
        target_payload = dict(target or {})
        target_id = str(target_payload.get("id", "")).strip() or str(case_id).strip()
        target_role = str(target_payload.get("role", "")).strip() or "patient"
        normalized_event_type = self._normalize_event_type(event_type or action)
        event = make_clinical_event(
            run_id=str(state.run_id).strip(),
            case_id=str(case_id).strip(),
            minute=int(state.current_minute or 0),
            tick=int(state.tick or 0),
            phase=str(action).strip() or str(zone).strip() or "tick",
            actor_id=normalized_actor or "system",
            actor_role=actor_role,
            target_id=target_id,
            target_role=target_role,
            event_type=normalized_event_type,
            action=str(action).strip(),
            location_id=str(location_id or self._default_location_id(runtime, actor)).strip(),
            resource_kind=actor_role,
            rationale=str(rationale).strip(),
            payload=dict(payload or {}),
            state_delta=self._state_delta(runtime),
            meta={"zone": str(zone).strip()},
            ordinal=len(list(state.event_log or [])) + 1,
        ).to_dict()
        event["zone"] = str(zone).strip()
        state.event_log.append(event)

    def _append_decision_snapshot(
        self,
        state: HospitalSchedulerState,
        runtime: HospitalCaseRuntime,
        *,
        proposed_type: str,
        proposed_target: str,
        alternatives: list[dict[str, Any]],
    ) -> None:
        snapshot_id = f"parallel_{str(runtime.case_id).strip()}_m{int(state.current_minute or 0)}"
        entry = {
            "snapshot_id": snapshot_id,
            "node": "parallel_scheduler_decision",
            "turn_index": int(runtime.er_turn_count or 0),
            "current_minute": int(state.current_minute or 0),
            "proposed_action": {
                "type": str(proposed_type).strip(),
                "target": str(proposed_target).strip(),
            },
            "alternatives": [dict(item or {}) for item in list(alternatives or [])],
            "rationale": str(runtime.latest_rationale).strip(),
            "state": self._state_delta(runtime),
        }
        existing = [
            item
            for item in list(runtime.decision_snapshots or [])
            if str(dict(item).get("snapshot_id", "")).strip() != snapshot_id
        ]
        existing.append(entry)
        runtime.decision_snapshots = existing[-8:]

    def _admit_arrivals(self, state: HospitalSchedulerState) -> None:
        remaining: list[str] = []
        for case_id in list(state.arrival_queue):
            runtime = state.case(case_id)
            if int(runtime.arrival_time_min or 0) > int(state.current_minute or 0):
                remaining.append(case_id)
                continue
            runtime.zone = "waiting_room"
            runtime.workflow_state = "waiting_triage"
            self._set_runtime_movement(
                runtime,
                current_location_id="arrival_entry_1",
                target_location_id="arrival_entry_1",
                interaction_location_id="triage_desk",
                movement_path=["arrival_entry_1"],
                pending_interaction={},
            )
            if case_id not in state.triage_queue:
                state.triage_queue.append(case_id)
            self._record_event(
                state,
                case_id=case_id,
                action="arrival_entered",
                zone=runtime.zone,
                actor="system",
                rationale="The patient has reached the ER arrival flow and is now waiting for triage.",
                event_type="case_started",
                location_id="arrival_entry_1",
            )
        state.arrival_queue = remaining

    def _assign_triage(self, state: HospitalSchedulerState) -> None:
        nurse = state.resources.first_available("triage_nurse", state.current_minute)
        if nurse is None or not state.triage_queue:
            return
        case_id = state.triage_queue.pop(0)
        runtime = state.case(case_id)
        runtime.zone = "waiting_room"
        runtime.workflow_state = "waiting_bed"
        runtime.latest_actor = nurse.resource_id
        runtime.latest_action = "perform_triage"
        runtime.latest_rationale = runtime.triage_rationale or "The hospital assigned triage severity at ER intake."
        runtime.effective_priority = int(runtime.triage_level or 3)
        self._set_runtime_movement(
            runtime,
            current_location_id="triage_desk",
            target_location_id="triage_queue_1",
            interaction_location_id="triage_desk",
            movement_path=["triage_desk", "triage_queue_1"],
            pending_interaction={},
        )
        state.bed_queue.append(case_id)
        nurse.status = "idle"
        nurse.available_minute = int(state.current_minute or 0)
        self._record_event(
            state,
            case_id=case_id,
            action="perform_triage",
            zone=runtime.zone,
            actor=nurse.resource_id,
            rationale=runtime.latest_rationale,
            event_type="triage_completed",
            location_id="triage_desk",
            payload={"triage_level": int(runtime.triage_level or 3)},
        )

    def _assign_beds(self, state: HospitalSchedulerState) -> None:
        remaining: list[str] = []
        for case_id in list(state.bed_queue):
            runtime = state.case(case_id)
            if runtime.assigned_bed_id:
                continue
            bed = self._first_free_bed(state)
            if bed is None:
                remaining.append(case_id)
                continue
            bed.status = "occupied"
            bed.assigned_case_id = case_id
            runtime.assigned_bed_id = bed.resource_id
            runtime.bed_assigned_min = int(state.current_minute or 0)
            runtime.zone = "er_workup"
            runtime.workflow_state = "waiting_er"
            bed_location_id = str(bed.location_id).strip()
            bedside_location_id = bed_location_id.replace("er_bed_", "er_bedside_") if bed_location_id.startswith("er_bed_") else bed_location_id
            self._set_runtime_movement(
                runtime,
                current_location_id=str(runtime.current_location_id).strip() or "triage_queue_1",
                target_location_id=bed_location_id,
                interaction_location_id=bedside_location_id,
                movement_path=[str(runtime.current_location_id).strip() or "triage_queue_1", bed_location_id],
                pending_interaction={},
            )
            if case_id not in state.er_queue:
                state.er_queue.append(case_id)
            self._record_event(
                state,
                case_id=case_id,
                action="bed_assigned",
                zone=runtime.zone,
                actor="system",
                rationale="A free ER bed was available, so the patient moved into ER workup.",
                event_type="bed_assigned",
                location_id=str(bed.location_id).strip(),
                payload={"bed_id": bed.resource_id},
            )
        state.bed_queue = remaining

    def _refresh_er_priorities(self, state: HospitalSchedulerState) -> None:
        for case_id in list(state.er_queue):
            runtime = state.case(case_id)
            dynamic_priority = self.queue_manager._dynamic_priority(
                {
                    "triage_level": runtime.triage_level,
                    "arrival_time_min": runtime.arrival_time_min,
                    "deterioration_risk": runtime.deterioration_risk,
                },
                state.current_minute,
            )
            runtime.effective_priority = int(
                dynamic_priority.get("effective_triage_level", runtime.triage_level) or runtime.triage_level or 3
            )

    def _assign_er_work(self, state: HospitalSchedulerState) -> None:
        doctor = state.resources.first_available("er_doctor", state.current_minute)
        if doctor is None or not state.er_queue:
            return
        eligible_cases = [
            state.case(case_id)
            for case_id in state.er_queue
            if int(state.current_minute or 0) > int(state.case(case_id).bed_assigned_min or 0)
        ]
        if not eligible_cases:
            return
        prioritized = sorted(
            eligible_cases,
            key=lambda runtime: (
                int(runtime.effective_priority or runtime.triage_level or 3),
                -int(runtime.waiting_minutes(state.current_minute) or 0),
                route_distance(
                    str(getattr(doctor, "location_id", "")).strip() or "er_doctor_station",
                    _bedside_location_for_runtime(runtime),
                ),
                int(runtime.arrival_time_min or 0),
                int(runtime.arrival_index or 0),
            ),
        )
        selected = prioritized[0]
        state.er_queue = [case_id for case_id in state.er_queue if case_id != selected.case_id]
        travel_duration = self._er_travel_duration_minutes()
        doctor.status = "busy"
        doctor.available_minute = int(state.current_minute or 0) + travel_duration
        doctor.assigned_case_id = selected.case_id
        selected.assigned_er_doctor_id = doctor.resource_id
        selected.zone = "er_workup"
        selected.workflow_state = "waiting_er_doctor_arrival"
        selected.latest_actor = doctor.resource_id
        selected.latest_action = "dispatch_er"
        selected.latest_rationale = (
            "The ER doctor selected this patient based on severity and wait time among currently bedded patients."
        )
        bed_id = str(selected.assigned_bed_id).strip() or "er_bed_1"
        bedside_location_id = bed_id.replace("er_bed_", "er_bedside_") if bed_id.startswith("er_bed_") else bed_id
        doctor_start_location_id = str(getattr(doctor, "location_id", "")).strip() or "er_doctor_station"
        selected.er_arrival_min = int(state.current_minute or 0) + travel_duration
        selected.er_started_min = 0
        self._set_runtime_movement(
            selected,
            current_location_id=bed_id,
            target_location_id=bed_id,
            interaction_location_id=bedside_location_id,
            movement_path=[bed_id, bedside_location_id],
            pending_interaction={
                "action": "perform_assessment",
                "actor_id": doctor.resource_id,
                "location_id": bedside_location_id,
                "ready_minute": int(state.current_minute or 0) + travel_duration,
            },
        )
        state.scheduled_events.append(
            {
                "event_type": "er_assessment_start",
                "case_id": selected.case_id,
                "execute_minute": int(state.current_minute or 0) + travel_duration,
                "doctor_id": doctor.resource_id,
            }
        )
        self._record_event(
            state,
            case_id=selected.case_id,
            action="dispatch_er",
            zone=selected.zone,
            actor=doctor.resource_id,
            rationale=selected.latest_rationale,
            event_type="assessment_completed",
            location_id=bedside_location_id,
            payload={"bedside_location_id": bedside_location_id, "doctor_start_location_id": doctor_start_location_id},
        )

    def _perform_er_assessment(
        self,
        state: HospitalSchedulerState,
        runtime: HospitalCaseRuntime,
        doctor: HospitalResource,
    ) -> None:
        policy_result = self.clinical_policy.evaluate_er_case(runtime, doctor_id=doctor.resource_id)
        runtime.target_department = str(policy_result.get("target_department", "")).strip()
        runtime.assessment_summary = str(policy_result.get("assessment_summary", "")).strip()
        runtime.latest_target = str(policy_result.get("target", runtime.target_department)).strip()
        alternatives = [dict(item or {}) for item in list(policy_result.get("alternatives", []) or [])]
        action = str(policy_result.get("action", "")).strip()
        rationale = str(policy_result.get("rationale", "")).strip()
        recommended_tests = [str(item).strip() for item in list(policy_result.get("recommended_tests", []) or []) if str(item).strip()]

        if action == "ask_history":
            question = str(policy_result.get("question", "")).strip()
            answer = str(policy_result.get("answer", "")).strip()
            runtime.question_history.append({"question": question, "answer": answer, "actor": doctor.resource_id})
            runtime.workflow_state = "waiting_er"
            runtime.latest_action = action
            runtime.latest_rationale = rationale
            self._append_decision_snapshot(
                state,
                runtime,
                proposed_type="ask_patient",
                proposed_target=question,
                alternatives=alternatives,
            )
            if runtime.case_id not in state.er_queue:
                state.er_queue.append(runtime.case_id)
            return

        if action == "order_test":
            runtime.recommended_tests = [
                test_name
                for test_name in recommended_tests
                if test_name not in runtime.recommended_tests and test_name not in runtime.completed_tests
            ]
            runtime.workflow_state = "waiting_test"
            runtime.latest_action = action
            runtime.latest_rationale = rationale
            self._append_decision_snapshot(
                state,
                runtime,
                proposed_type="request_test",
                proposed_target=runtime.recommended_tests[0] if runtime.recommended_tests else "",
                alternatives=alternatives,
            )
            if runtime.case_id not in state.test_queue:
                state.test_queue.append(runtime.case_id)
            return

        if action == "await_results":
            runtime.workflow_state = "awaiting_results"
            runtime.latest_action = action
            runtime.latest_rationale = rationale
            return

        if action == "request_specialty":
            runtime.workflow_state = "waiting_specialty"
            runtime.latest_action = action
            runtime.latest_rationale = rationale
            self._append_decision_snapshot(
                state,
                runtime,
                proposed_type="consult_specialty",
                proposed_target=str(runtime.target_department).strip(),
                alternatives=alternatives,
            )
            if runtime.case_id not in state.specialty_queue:
                state.specialty_queue.append(runtime.case_id)
            return

        runtime.latest_action = "er_finalize"
        runtime.latest_rationale = rationale
        self._append_decision_snapshot(
            state,
            runtime,
            proposed_type="diagnose",
            proposed_target=str(runtime.assessment_summary).strip(),
            alternatives=alternatives,
        )
        self._complete_case_from_er(state, runtime)

    def _start_requested_tests(self, state: HospitalSchedulerState) -> None:
        remaining: list[str] = []
        for case_id in list(state.test_queue):
            runtime = state.case(case_id)
            if runtime.pending_results:
                continue
            next_test = self._next_unstarted_test(runtime)
            if not next_test:
                if case_id not in state.er_queue and not runtime.is_completed:
                    state.er_queue.append(case_id)
                continue
            resource_type = self._resource_type_for_test(next_test)
            resource = state.resources.first_available(resource_type, state.current_minute)
            if resource is None:
                remaining.append(case_id)
                continue
            resource.status = "busy"
            resource.assigned_case_id = case_id
            duration = self._test_duration_minutes(resource_type)
            resource.available_minute = int(state.current_minute or 0) + duration
            runtime.pending_results.append(
                {
                    "test_name": next_test,
                    "resource_id": resource.resource_id,
                    "resource_type": resource_type,
                    "ready_minute": int(state.current_minute or 0) + duration,
                }
            )
            runtime.zone = "awaiting_results"
            runtime.workflow_state = "awaiting_results"
            wait_location_id = self._wait_location_for_resource_type(resource_type)
            self._set_runtime_movement(
                runtime,
                current_location_id=str(runtime.assigned_bed_id).strip() or "er_bed_1",
                target_location_id=wait_location_id,
                interaction_location_id=wait_location_id,
                movement_path=[str(runtime.assigned_bed_id).strip() or "er_bed_1", wait_location_id],
                pending_interaction={},
            )
            self._record_event(
                state,
                case_id=case_id,
                action="test_started",
                zone=runtime.zone,
                actor=resource.resource_id,
                rationale=f"{next_test} was started because ER still needed objective evidence before discharge or specialty handoff.",
                event_type="test_ordered",
                location_id=str(resource.location_id).strip(),
                payload={"requested_test": next_test, "resource_type": resource_type},
            )
            state.scheduled_events.append(
                {
                    "event_type": "test_result_ready",
                    "case_id": case_id,
                    "execute_minute": int(state.current_minute or 0) + duration,
                    "test_name": next_test,
                    "resource_id": resource.resource_id,
                    "resource_type": resource_type,
                }
            )
        state.test_queue = remaining

    def _assign_specialty_work(self, state: HospitalSchedulerState) -> None:
        if not state.specialty_queue:
            return
        remaining: list[str] = []
        for case_id in list(state.specialty_queue):
            runtime = state.case(case_id)
            department = normalize_department(runtime.target_department, default="")
            specialist = self._find_available_specialist(state, department)
            if specialist is None:
                remaining.append(case_id)
                continue
            travel_duration = self._specialty_travel_duration_minutes()
            consult_duration = self._specialty_consult_duration_minutes()
            specialist.status = "busy"
            specialist.assigned_case_id = case_id
            specialist.available_minute = int(state.current_minute or 0) + travel_duration + consult_duration
            runtime.assigned_specialist_id = specialist.resource_id
            runtime.assigned_consult_room_id = ""
            runtime.specialty_arrival_min = int(state.current_minute or 0) + travel_duration
            runtime.specialty_started_min = 0
            bedside_location_id = _bedside_location_for_runtime(runtime)
            specialist_start_location_id = str(getattr(specialist, "location_id", "")).strip() or str(specialist.resource_id).replace("specialty_", "sidebar_")
            self._set_runtime_movement(
                runtime,
                current_location_id=str(runtime.assigned_bed_id).strip() or "er_bed_1",
                target_location_id=str(runtime.assigned_bed_id).strip() or "er_bed_1",
                interaction_location_id=bedside_location_id,
                movement_path=[str(runtime.assigned_bed_id).strip() or "er_bed_1", bedside_location_id],
                pending_interaction={
                    "action": "consult_started",
                    "actor_id": specialist.resource_id,
                    "location_id": bedside_location_id,
                    "ready_minute": int(state.current_minute or 0) + travel_duration,
                },
            )
            state.scheduled_events.append(
                {
                    "event_type": "specialty_consult_start",
                    "case_id": case_id,
                    "execute_minute": int(state.current_minute or 0) + travel_duration,
                    "department": department,
                    "specialist_id": specialist.resource_id,
                    "specialist_start_location_id": specialist_start_location_id,
                }
            )
        state.specialty_queue = remaining

    def _process_scheduled_events(self, state: HospitalSchedulerState) -> None:
        pending = list(state.scheduled_events)
        state.scheduled_events = []
        remaining: list[dict[str, Any]] = []
        for event in pending:
            if int(event.get("execute_minute", 0) or 0) > int(state.current_minute or 0):
                remaining.append(event)
                continue
            event_type = str(event.get("event_type", "")).strip()
            if event_type == "test_result_ready":
                self._handle_test_result_event(state, event)
            elif event_type == "er_assessment_start":
                self._handle_er_assessment_start_event(state, event)
            elif event_type == "specialty_consult_start":
                self._handle_specialty_start_event(state, event)
            elif event_type == "specialty_consult_complete":
                self._handle_specialty_complete_event(state, event)
            elif event_type == "return_from_results":
                self._handle_return_from_results_event(state, event)
        state.scheduled_events = remaining + list(state.scheduled_events)

    def _handle_er_assessment_start_event(self, state: HospitalSchedulerState, event: dict[str, Any]) -> None:
        case_id = str(event.get("case_id", "")).strip()
        doctor_id = str(event.get("doctor_id", "")).strip()
        if not case_id or not doctor_id:
            return
        runtime = state.case(case_id)
        doctor = state.resources.find_by_id(doctor_id)
        if doctor is None:
            return
        doctor.status = "busy"
        doctor.assigned_case_id = case_id
        doctor.available_minute = int(state.current_minute or 0) + 1
        runtime.zone = "er_workup"
        runtime.workflow_state = "in_er_interview"
        runtime.latest_actor = doctor.resource_id
        runtime.latest_action = "perform_assessment"
        runtime.er_turn_count += 1
        runtime.er_started_min = int(state.current_minute or 0)
        bedside_location_id = _bedside_location_for_runtime(runtime)
        doctor.location_id = bedside_location_id
        self._set_runtime_movement(
            runtime,
            current_location_id=str(runtime.assigned_bed_id).strip() or "er_bed_1",
            target_location_id=str(runtime.assigned_bed_id).strip() or "er_bed_1",
            interaction_location_id=bedside_location_id,
            movement_path=[bedside_location_id],
            pending_interaction={},
        )
        self._perform_er_assessment(state, runtime, doctor)
        if runtime.latest_action in {"er_finalize", "specialty_finalize", "specialty_consult"}:
            return
        payload: dict[str, Any] = {}
        event_type = runtime.latest_action or "perform_assessment"
        location_id = bedside_location_id
        if runtime.latest_action == "ask_history":
            last_question = dict(runtime.question_history[-1] if runtime.question_history else {})
            payload = {
                "question": str(last_question.get("question", "")).strip(),
                "answer": str(last_question.get("answer", "")).strip(),
            }
            event_type = "question_asked"
        elif runtime.latest_action == "order_test":
            payload = {
                "requested_test": runtime.recommended_tests[0] if runtime.recommended_tests else "",
            }
            event_type = "test_ordered"
        elif runtime.latest_action == "await_results":
            payload = {
                "pending_results_count": len(list(runtime.pending_results or [])),
            }
            event_type = "awaiting_results"
        elif runtime.latest_action == "request_specialty":
            payload = {
                "department": str(runtime.target_department).strip(),
            }
            event_type = "consult_requested"
        self._record_event(
            state,
            case_id=runtime.case_id,
            action=runtime.latest_action or "perform_assessment",
            zone=runtime.zone,
            actor=doctor.resource_id,
            rationale=runtime.latest_rationale,
            event_type=event_type,
            location_id=location_id,
            payload=payload,
        )

    def _handle_specialty_start_event(self, state: HospitalSchedulerState, event: dict[str, Any]) -> None:
        case_id = str(event.get("case_id", "")).strip()
        if not case_id:
            return
        runtime = state.case(case_id)
        department = normalize_department(str(event.get("department", "")).strip(), default=runtime.target_department or "general_medicine")
        specialist_id = str(event.get("specialist_id", "")).strip()
        consult_plan = self.specialty_policy.plan_consult(
            runtime,
            specialist_id=specialist_id,
            consult_room_id="er_bed_consult",
        )
        runtime.zone = "er_workup"
        runtime.workflow_state = "in_specialty_consult"
        runtime.latest_actor = specialist_id
        runtime.latest_action = "specialty_consult"
        runtime.latest_rationale = str(consult_plan.get("rationale", "")).strip()
        runtime.specialty_turn_count += 1
        runtime.specialty_started_min = int(state.current_minute or 0)
        bedside_location_id = _bedside_location_for_runtime(runtime)
        specialist = state.resources.find_by_id(specialist_id)
        if specialist is not None:
            specialist.location_id = bedside_location_id
        self._set_runtime_movement(
            runtime,
            current_location_id=str(runtime.assigned_bed_id).strip() or "er_bed_1",
            target_location_id=str(runtime.assigned_bed_id).strip() or "er_bed_1",
            interaction_location_id=bedside_location_id,
            movement_path=[bedside_location_id],
            pending_interaction={},
        )
        self._record_event(
            state,
            case_id=case_id,
            action="consult_started",
            zone=runtime.zone,
            actor=specialist_id,
            rationale=runtime.latest_rationale,
            event_type="consult_started",
            location_id=str(runtime.assigned_bed_id).strip() or "er_bed_1",
            payload={
                **dict(consult_plan.get("payload", {}) or {}),
                "department": department,
                "specialist_id": specialist_id,
            },
            target={"id": runtime.case_id, "role": "patient"},
        )
        state.scheduled_events.append(
            {
                "event_type": "specialty_consult_complete",
                "case_id": case_id,
                "execute_minute": int(state.current_minute or 0) + self._specialty_consult_duration_minutes(),
                "department": department,
                "specialist_id": specialist_id,
            }
        )

    def _handle_test_result_event(self, state: HospitalSchedulerState, event: dict[str, Any]) -> None:
        case_id = str(event.get("case_id", "")).strip()
        if not case_id:
            return
        runtime = state.case(case_id)
        test_name = str(event.get("test_name", "")).strip()
        resource = state.resources.find_by_id(str(event.get("resource_id", "")).strip())
        if resource is not None:
            resource.status = "idle"
            resource.assigned_case_id = ""
            resource.available_minute = int(state.current_minute or 0)
        runtime.pending_results = [
            item
            for item in runtime.pending_results
            if str(item.get("test_name", "")).strip() != test_name
        ]
        if test_name and test_name not in runtime.completed_tests:
            runtime.completed_tests.append(test_name)
        result_summary = self.clinical_policy.build_test_result_summary(runtime, test_name)
        runtime.test_results.append(result_summary)
        finding = self.clinical_policy.build_objective_finding(runtime, test_name)
        if finding:
            runtime.objective_findings.append(finding)
        runtime.workflow_state = "result_ready_hold"
        runtime.zone = "awaiting_results"
        runtime.latest_action = "test_result_ready"
        runtime.latest_rationale = "The test result is now visible in diagnostics before the patient returns to ER review."
        wait_location_id = self._wait_location_for_resource_type(str(event.get("resource_type", "")).strip())
        self._set_runtime_movement(
            runtime,
            current_location_id=wait_location_id,
            target_location_id=wait_location_id,
            interaction_location_id=wait_location_id,
            movement_path=[wait_location_id],
            pending_interaction={
                "action": "review_results",
                "actor_id": str(runtime.assigned_er_doctor_id).strip() or "doctor_er_0",
                "location_id": _bedside_location_for_runtime(runtime),
                "ready_minute": int(state.current_minute or 0) + 3,
            },
        )
        self._record_event(
            state,
            case_id=runtime.case_id,
            action="test_result_ready",
            zone=runtime.zone,
            actor=str(event.get("resource_id", "")).strip() or "system",
            rationale=runtime.latest_rationale,
            event_type="result_received",
            location_id=str(resource.location_id).strip() if resource is not None else self._default_location_id(runtime, str(event.get("resource_id", "")).strip() or "system"),
            payload={
                "requested_test": test_name,
                "pending_results_count": len(list(runtime.pending_results or [])),
                "test_result": result_summary,
            },
        )
        state.scheduled_events.append(
            {
                "event_type": "return_from_results",
                "case_id": case_id,
                "execute_minute": int(state.current_minute or 0) + 3,
            }
        )

    def _handle_return_from_results_event(self, state: HospitalSchedulerState, event: dict[str, Any]) -> None:
        case_id = str(event.get("case_id", "")).strip()
        if not case_id:
            return
        runtime = state.case(case_id)
        if runtime.is_completed:
            return
        runtime.workflow_state = "waiting_er"
        runtime.zone = "er_workup"
        runtime.latest_action = "review_results"
        runtime.latest_rationale = "The diagnostic result has been displayed, and the patient returns to the ER queue for bedside review."
        self._set_runtime_movement(
            runtime,
            current_location_id=str(runtime.current_location_id).strip() or "lab_wait_1",
            target_location_id=str(runtime.assigned_bed_id).strip() or "er_bed_1",
            interaction_location_id=_bedside_location_for_runtime(runtime),
            movement_path=[
                str(runtime.current_location_id).strip() or "lab_wait_1",
                str(runtime.assigned_bed_id).strip() or "er_bed_1",
            ],
            pending_interaction={},
        )
        if runtime.case_id not in state.er_queue:
            state.er_queue.append(runtime.case_id)
        self._record_event(
            state,
            case_id=runtime.case_id,
            action="review_results",
            zone=runtime.zone,
            actor=runtime.assigned_er_doctor_id or "doctor_er_0",
            rationale=runtime.latest_rationale,
            event_type="assessment_completed",
            location_id=str(runtime.assigned_bed_id).strip() or "er_bed_1",
            payload={
                "pending_results_count": len(list(runtime.pending_results or [])),
                "latest_result": dict(runtime.test_results[-1] if runtime.test_results else {}),
            },
        )

    def _handle_specialty_complete_event(self, state: HospitalSchedulerState, event: dict[str, Any]) -> None:
        case_id = str(event.get("case_id", "")).strip()
        if not case_id:
            return
        runtime = state.case(case_id)
        department = normalize_department(str(event.get("department", "")).strip(), default=runtime.target_department or "general_medicine")
        specialist_id = str(event.get("specialist_id", "")).strip()
        completion = self.specialty_policy.complete_consult(
            runtime,
            department=department,
            specialist_id=specialist_id,
        )
        consult_note = str(completion.get("consult_note", "")).strip()
        runtime.consult_history.append(
            {
                "department": str(completion.get("department", department)).strip(),
                "opinion": consult_note,
                "actor": specialist_id,
            }
        )
        runtime.latest_action = "specialty_finalize"
        runtime.latest_actor = specialist_id
        runtime.latest_rationale = str(completion.get("rationale", "")).strip()
        if str(completion.get("final_diagnosis", "")).strip():
            runtime.assessment_summary = str(completion.get("final_diagnosis", "")).strip()
        self._complete_case(state, runtime, actor=specialist_id or "specialist", action="specialty_finalize")

    def _release_completed_resource_windows(self, state: HospitalSchedulerState) -> None:
        for collection in (
            state.resources.triage_nurses,
            state.resources.er_doctors,
            state.resources.lab_slots,
            state.resources.imaging_slots,
            state.resources.specialists,
            state.resources.consult_rooms,
        ):
            for resource in collection:
                if str(resource.status).strip() == "idle":
                    continue
                if int(resource.available_minute or 0) > int(state.current_minute or 0):
                    continue
                resource.status = "idle"
                resource.assigned_case_id = ""

    @staticmethod
    def _ensure_unique_queue(queue: list[str], case_id: str) -> list[str]:
        normalized = str(case_id).strip()
        result = [str(item).strip() for item in list(queue or []) if str(item).strip() and str(item).strip() != normalized]
        result.append(normalized)
        return result

    @staticmethod
    def _normalize_event_type(event_type: str) -> str:
        normalized = str(event_type).strip()
        mapping = {
            "arrival_entered": "arrival_entered",
            "case_started": "case_started",
            "triage_completed": "triage_completed",
            "bed_assigned": "patient_moved",
            "question_asked": "question_asked",
            "test_ordered": "test_ordered",
            "awaiting_results": "assessment_completed",
            "consult_requested": "consult_requested",
            "consult_started": "consult_started",
            "result_received": "result_received",
            "case_completed": "case_completed",
        }
        return mapping.get(normalized, "assessment_completed")

    def _next_unstarted_test(self, runtime: HospitalCaseRuntime) -> str:
        for test_name in runtime.recommended_tests:
            if test_name in runtime.completed_tests:
                continue
            if any(str(item.get("test_name", "")).strip() == test_name for item in runtime.pending_results):
                continue
            return test_name
        return ""

    def _resource_type_for_test(self, test_name: str) -> str:
        normalized = str(test_name).strip().lower()
        if any(keyword in normalized for keyword in ("ct", "mri", "xray", "x-ray", "imaging", "ultrasound")):
            return "imaging_slot"
        return "lab_slot"

    def _test_duration_minutes(self, resource_type: str) -> int:
        if resource_type == "imaging_slot":
            return 6
        return 5

    def _specialty_travel_duration_minutes(self) -> int:
        return 2

    def _er_travel_duration_minutes(self) -> int:
        return 1

    def _specialty_consult_duration_minutes(self) -> int:
        return 4

    def _find_available_specialist(self, state: HospitalSchedulerState, department: str) -> HospitalResource | None:
        normalized = normalize_department(department, default="")
        for resource in state.resources.specialists:
            if not resource.is_available(state.current_minute):
                continue
            resource_department = normalize_department(str(resource.resource_id).replace("specialty_", ""), default="")
            if resource_department == normalized:
                return resource
        return None

    def _complete_case_from_er(self, state: HospitalSchedulerState, runtime: HospitalCaseRuntime) -> None:
        runtime.latest_action = "er_finalize"
        runtime.latest_rationale = (
            "ER gathered enough targeted history and objective evidence to finish without additional specialty escalation."
        )
        self._complete_case(state, runtime, actor=runtime.assigned_er_doctor_id or "doctor_er_0", action="er_finalize")

    def _complete_case(self, state: HospitalSchedulerState, runtime: HospitalCaseRuntime, *, actor: str, action: str) -> None:
        runtime.is_completed = True
        runtime.workflow_state = "completed"
        runtime.zone = "discharged"
        discharge_origin = str(runtime.assigned_bed_id).strip() or str(runtime.current_location_id).strip() or "er_bed_1"
        self._set_runtime_movement(
            runtime,
            current_location_id=discharge_origin,
            target_location_id="discharge_1",
            interaction_location_id="discharge_1",
            movement_path=[discharge_origin, "discharge_1"],
            pending_interaction={},
        )
        state.resources.release_case(runtime.case_id, state.current_minute)
        bed = state.resources.find_by_id(runtime.assigned_bed_id)
        if bed is not None:
            bed.assigned_case_id = ""
            bed.status = "idle"
            bed.available_minute = int(state.current_minute or 0)
        self._record_event(
            state,
            case_id=runtime.case_id,
            action=action,
            zone=runtime.zone,
            actor=actor,
            rationale=runtime.latest_rationale,
            event_type="case_completed" if action in {"er_finalize", "specialty_finalize"} else action,
            location_id="discharge_1",
            payload={
                "final_diagnosis": str(runtime.assessment_summary).strip(),
                "final_department": str(runtime.target_department).strip(),
            },
        )

    @staticmethod
    def _first_free_bed(state: HospitalSchedulerState) -> HospitalResource | None:
        for bed in state.resources.er_beds:
            if str(bed.assigned_case_id).strip():
                continue
            return bed
        return None
