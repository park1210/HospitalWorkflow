from __future__ import annotations

from typing import Any

from app.core.resource_manager import ResourceManager
from app.core.state import record_deterioration_event, record_resource_event, record_time_event
from app.modules.deterioration_module import DeteriorationModule


class TimeEngine:
    def __init__(self, shared_resource_state: dict[str, Any] | None = None) -> None:
        self.deterioration_module = DeteriorationModule()
        self.resource_manager = ResourceManager()
        self.shared_resource_state = shared_resource_state

    @staticmethod
    def _get_state_value(state: Any, key: str, default: Any = None) -> Any:
        if isinstance(state, dict):
            return state.get(key, default)
        return getattr(state, key, default)

    @staticmethod
    def _set_state_value(state: Any, key: str, value: Any) -> None:
        if isinstance(state, dict):
            state[key] = value
            return
        setattr(state, key, value)

    def release_ready_results(self, state: Any) -> list[dict[str, Any]]:
        pending_results = list(self._get_state_value(state, "pending_results", []) or [])
        if not pending_results:
            return []

        current_time_min = int(self._get_state_value(state, "current_time_min", 0) or 0)
        ready: list[dict[str, Any]] = []
        still_pending: list[dict[str, Any]] = []

        for item in pending_results:
            ready_time_min = int(item.get("ready_time_min", 0) or 0)
            if ready_time_min <= current_time_min:
                ready.append(item)
            else:
                still_pending.append(item)

        if not ready:
            return []

        self._set_state_value(state, "pending_results", still_pending)
        objective_findings = list(self._get_state_value(state, "objective_findings", []) or [])
        known_information = list(self._get_state_value(state, "known_information", []) or [])
        for item in ready:
            finding = str(item.get("finding", "")).strip()
            if finding and finding not in objective_findings:
                objective_findings.append(finding)
            if finding and finding not in known_information:
                known_information.append(finding)
        self._set_state_value(state, "objective_findings", objective_findings)
        self._set_state_value(state, "known_information", known_information)

        for item in ready:
            finding = str(item.get("finding", "")).strip()
            record_time_event(
                state,
                {
                    "actor": "system",
                    "action": "test_result_available",
                    "target": str(item.get("resolved_name", "")).strip() or str(item.get("requested_test", "")).strip(),
                    "minutes_elapsed": 0,
                    "start_time_min": current_time_min,
                    "end_time_min": current_time_min,
                    "wait_min": 0,
                    "service_time_min": 0,
                    "resource_kind": str(item.get("resource_kind", "")).strip(),
                    "rationale": f"Pending test result became available at minute {current_time_min}.",
                },
            )
        return ready

    def next_pending_result_wait(self, state: Any) -> int | None:
        pending_results = list(self._get_state_value(state, "pending_results", []) or [])
        if not pending_results:
            return None
        current_time_min = int(self._get_state_value(state, "current_time_min", 0) or 0)
        ready_times = sorted(int(item.get("ready_time_min", current_time_min) or current_time_min) for item in pending_results)
        next_ready = ready_times[0]
        return max(0, next_ready - current_time_min)

    def schedule_pending_result(
        self,
        state: Any,
        *,
        requested_test: str,
        resolved_name: str,
        result_text: str,
        pending_result_plan: dict[str, Any],
    ) -> dict[str, Any]:
        current_time_min = int(self._get_state_value(state, "current_time_min", 0) or 0)
        ready_time_min = int(
            pending_result_plan.get("ready_time_min", current_time_min) or current_time_min
        )
        finding = f"{resolved_name or requested_test}: {result_text}"
        pending_item = {
            "requested_test": str(requested_test).strip(),
            "resolved_name": str(resolved_name or requested_test).strip(),
            "result_text": str(result_text).strip(),
            "finding": finding,
            "resource_kind": str(pending_result_plan.get("resource_kind", "")).strip(),
            "ready_time_min": ready_time_min,
        }
        pending_results = list(self._get_state_value(state, "pending_results", []) or [])
        pending_results.append(pending_item)
        self._set_state_value(state, "pending_results", pending_results)
        record_resource_event(
            state,
            {
                "actor": "system",
                "action": "pending_test_result",
                "target": pending_item["resolved_name"],
                "resource_kind": pending_item["resource_kind"],
                "slot_index": int(pending_result_plan.get("slot_index", 0) or 0),
                "capacity": int(pending_result_plan.get("capacity", 1) or 1),
                "wait_min": int(pending_result_plan.get("wait_min", 0) or 0),
                "service_time_min": int(pending_result_plan.get("service_time_min", 0) or 0),
                "service_time_source": str(pending_result_plan.get("service_time_source", "")).strip(),
                "actual_start_min": int(pending_result_plan.get("actual_start_min", ready_time_min) or ready_time_min),
                "end_time_min": ready_time_min,
            },
        )
        return pending_item

    def advance_time(
        self,
        case: dict[str, Any],
        state: Any,
        *,
        actor: str,
        action: str,
        target: str = "",
        rationale: str = "",
    ) -> dict[str, Any]:
        start_time_min = int(self._get_state_value(state, "current_time_min", 0) or 0)
        resource_plan = self.resource_manager.plan_action(
            case,
            state,
            actor=actor,
            action=action,
            target=target,
            start_time_min=start_time_min,
            shared_resource_state=self.shared_resource_state,
        )
        if self.shared_resource_state is not None:
            self._set_state_value(
                state,
                "resource_status",
                {
                name: {
                    "capacity": int((details or {}).get("capacity", 1) or 1),
                    "next_available_times": list((details or {}).get("next_available_times", []) or []),
                }
                for name, details in self.shared_resource_state.items()
                },
            )
        wait_min = int(resource_plan.get("wait_min", 0) or 0)
        service_time_min = int(resource_plan.get("service_time_min", 0) or 0)
        minutes = wait_min + service_time_min
        end_time_min = int(resource_plan.get("end_time_min", start_time_min + minutes) or (start_time_min + minutes))

        self._set_state_value(state, "current_time_min", end_time_min)
        self._set_state_value(state, "last_seen_time_min", end_time_min)

        resource_event = {
            "actor": str(actor).strip(),
            "action": str(action).strip(),
            "target": str(target).strip(),
            "resource_kind": str(resource_plan.get("resource_kind", "")).strip(),
            "slot_index": int(resource_plan.get("slot_index", 0) or 0),
            "capacity": int(resource_plan.get("capacity", 1) or 1),
            "wait_min": wait_min,
            "service_time_min": service_time_min,
            "service_time_source": str(resource_plan.get("service_time_source", "")).strip(),
            "actual_start_min": int(resource_plan.get("actual_start_min", start_time_min) or start_time_min),
            "end_time_min": end_time_min,
        }
        record_resource_event(state, resource_event)

        time_event = {
            "actor": str(actor).strip(),
            "action": str(action).strip(),
            "target": str(target).strip(),
            "minutes_elapsed": minutes,
            "start_time_min": start_time_min,
            "end_time_min": end_time_min,
            "wait_min": wait_min,
            "service_time_min": service_time_min,
            "resource_kind": str(resource_plan.get("resource_kind", "")).strip(),
            "rationale": str(rationale).strip(),
        }
        record_time_event(state, time_event)

        deterioration_result = self.deterioration_module.advance(
            case,
            state,
            start_time_min=start_time_min,
            end_time_min=end_time_min,
            triggering_action=action,
        )
        for event in deterioration_result.get("applied_events", []) or []:
            record_deterioration_event(state, event)

        return {
            "minutes_elapsed": minutes,
            "start_time_min": start_time_min,
            "end_time_min": end_time_min,
            "wait_min": wait_min,
            "service_time_min": service_time_min,
            "resource_kind": str(resource_plan.get("resource_kind", "")).strip(),
            "resource_event": resource_event,
            "deterioration_events": list(deterioration_result.get("applied_events", []) or []),
            "updated_vitals": dict(deterioration_result.get("updated_vitals", {}) or {}),
            "pending_result_plan": dict(resource_plan.get("pending_result_plan", {}) or {}),
        }

    def advance_passive_time(
        self,
        case: dict[str, Any],
        state: Any,
        *,
        minutes: int,
        reason: str,
        action: str = "waiting_in_queue",
    ) -> dict[str, Any]:
        start_time_min = int(self._get_state_value(state, "current_time_min", 0) or 0)
        end_time_min = start_time_min + int(minutes or 0)
        self._set_state_value(state, "current_time_min", end_time_min)
        self._set_state_value(state, "last_seen_time_min", end_time_min)

        time_event = {
            "actor": "system",
            "action": str(action).strip(),
            "target": "",
            "minutes_elapsed": int(minutes or 0),
            "start_time_min": start_time_min,
            "end_time_min": end_time_min,
            "wait_min": int(minutes or 0),
            "service_time_min": 0,
            "resource_kind": "queue",
            "rationale": str(reason).strip(),
        }
        record_time_event(state, time_event)

        deterioration_result = self.deterioration_module.advance(
            case,
            state,
            start_time_min=start_time_min,
            end_time_min=end_time_min,
            triggering_action=action,
        )
        for event in deterioration_result.get("applied_events", []) or []:
            record_deterioration_event(state, event)

        return {
            "minutes_elapsed": int(minutes or 0),
            "start_time_min": start_time_min,
            "end_time_min": end_time_min,
            "deterioration_events": list(deterioration_result.get("applied_events", []) or []),
            "updated_vitals": dict(deterioration_result.get("updated_vitals", {}) or {}),
        }
