from __future__ import annotations

from typing import Any


class ResourceManager:
    DEFAULT_CAPACITY = {
        "doctor": 1,
        "imaging": 1,
        "lab": 1,
        "consult": 1,
    }

    DEFAULT_SERVICE_TIMES_MIN = {
        "doctor": 5,
        "test_order": 2,
        "imaging": 25,
        "blood_tests": 12,
        "urinalysis": 10,
        "consult": 20,
        "stabilization": 8,
    }

    def _resource_profile(self, case: dict[str, Any]) -> dict[str, Any]:
        profile = case.get("resource_profile", {})
        return profile if isinstance(profile, dict) else {}

    def _ensure_status(
        self,
        state: Any,
        case: dict[str, Any],
        *,
        shared_resource_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if shared_resource_state is not None:
            current = shared_resource_state or {}
        else:
            current = getattr(state, "resource_status", {}) or {}
        if current:
            return current

        profile = self._resource_profile(case)
        capacities = profile.get("capacity", {}) if isinstance(profile.get("capacity", {}), dict) else {}
        status: dict[str, Any] = {}
        for resource_name, default_capacity in self.DEFAULT_CAPACITY.items():
            capacity = int(capacities.get(resource_name, default_capacity) or default_capacity)
            status[resource_name] = {
                "capacity": max(capacity, 1),
                "next_available_times": [0 for _ in range(max(capacity, 1))],
            }
        if shared_resource_state is not None:
            shared_resource_state.update(status)
            current = shared_resource_state
        else:
            state.resource_status = status
            current = status
        return current

    def _choose_slot(self, slot_times: list[int], start_time_min: int) -> tuple[int, int]:
        indexed = sorted(enumerate(slot_times), key=lambda item: (item[1], item[0]))
        slot_index, available_time = indexed[0]
        actual_start = max(start_time_min, int(available_time or 0))
        wait_min = max(0, actual_start - start_time_min)
        return slot_index, wait_min

    def _normalize_target_key(self, target: str) -> str:
        return str(target).strip().lower().replace(" ", "_")

    def _specialty_resource_kind(self, actor: str) -> str:
        normalized_actor = self._normalize_target_key(actor or "specialty_service")
        return f"specialty_{normalized_actor}"

    def _test_service_time(self, case: dict[str, Any], target: str) -> tuple[int, str]:
        profile = self._resource_profile(case)
        turnaround = profile.get("test_turnaround", {}) if isinstance(profile.get("test_turnaround", {}), dict) else {}
        normalized_target = self._normalize_target_key(target)

        for key, value in turnaround.items():
            normalized_key = self._normalize_target_key(str(key))
            if normalized_key == normalized_target:
                return int(value or self.DEFAULT_SERVICE_TIMES_MIN["imaging"]), "test_turnaround"
            if normalized_key and normalized_key in normalized_target:
                return int(value or self.DEFAULT_SERVICE_TIMES_MIN["imaging"]), "test_turnaround"

        target_text = normalized_target
        if any(term in target_text for term in ("mri", "ct", "xray", "x-ray", "ultrasound", "scan", "imaging", "radiograph")):
            return self.DEFAULT_SERVICE_TIMES_MIN["imaging"], "default_imaging"
        if any(term in target_text for term in ("blood", "cbc", "bmp", "cmp", "lab", "serology")):
            return self.DEFAULT_SERVICE_TIMES_MIN["blood_tests"], "default_blood"
        if any(term in target_text for term in ("urine", "urinalysis")):
            return self.DEFAULT_SERVICE_TIMES_MIN["urinalysis"], "default_urinalysis"
        return 15, "default_test"

    def _consult_service_time(self, case: dict[str, Any], target: str) -> tuple[int, str]:
        profile = self._resource_profile(case)
        turnaround = profile.get("consult_turnaround", {}) if isinstance(profile.get("consult_turnaround", {}), dict) else {}
        normalized_target = self._normalize_target_key(target)
        for key, value in turnaround.items():
            normalized_key = self._normalize_target_key(str(key))
            if normalized_key == normalized_target:
                return int(value or self.DEFAULT_SERVICE_TIMES_MIN["consult"]), "consult_turnaround"
            if normalized_key and normalized_key in normalized_target:
                return int(value or self.DEFAULT_SERVICE_TIMES_MIN["consult"]), "consult_turnaround"
        return self.DEFAULT_SERVICE_TIMES_MIN["consult"], "default_consult"

    def _allocate_resource(
        self,
        status: dict[str, Any],
        resource_kind: str,
        *,
        start_time_min: int,
        service_time_min: int,
    ) -> dict[str, Any]:
        resource_state = status.get(resource_kind, {"capacity": 1, "next_available_times": [0]})
        slot_times = list(resource_state.get("next_available_times", [0]) or [0])
        slot_index, wait_min = self._choose_slot(slot_times, start_time_min)
        actual_start_min = start_time_min + wait_min
        end_time_min = actual_start_min + int(service_time_min)
        slot_times[slot_index] = end_time_min
        resource_state["next_available_times"] = slot_times
        status[resource_kind] = resource_state
        return {
            "resource_kind": resource_kind,
            "slot_index": slot_index,
            "wait_min": wait_min,
            "service_time_min": int(service_time_min),
            "actual_start_min": actual_start_min,
            "end_time_min": end_time_min,
            "capacity": int(resource_state.get("capacity", 1) or 1),
        }

    def plan_action(
        self,
        case: dict[str, Any],
        state: Any,
        *,
        actor: str,
        action: str,
        target: str,
        start_time_min: int,
        shared_resource_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        status = self._ensure_status(state, case, shared_resource_state=shared_resource_state)
        normalized_action = str(action).strip().lower()
        normalized_target = str(target).strip()
        normalized_actor = str(actor).strip().lower()

        if normalized_action in {"perform_triage", "perform_assessment", "ask_patient", "make_diagnostic_summary", "diagnose", "diagnose_now", "refine_again"}:
            resource_kind = "doctor" if normalized_actor == "er_department" else self._specialty_resource_kind(normalized_actor)
            service_time_min = self.DEFAULT_SERVICE_TIMES_MIN["doctor"]
            service_time_source = "default_doctor"
        elif normalized_action == "stabilize":
            resource_kind = "doctor"
            service_time_min = self.DEFAULT_SERVICE_TIMES_MIN["stabilization"]
            service_time_source = "default_stabilization"
        elif normalized_action == "request_test":
            target_key = self._normalize_target_key(normalized_target)
            if any(term in target_key for term in ("mri", "ct", "xray", "x-ray", "ultrasound", "scan", "imaging", "radiograph", "electromyography")):
                test_resource_kind = "imaging"
            else:
                test_resource_kind = "lab"
            turnaround_min, turnaround_source = self._test_service_time(case, normalized_target)
            doctor_plan = self._allocate_resource(
                status,
                "doctor",
                start_time_min=start_time_min,
                service_time_min=self.DEFAULT_SERVICE_TIMES_MIN["test_order"],
            )
            test_plan = self._allocate_resource(
                status,
                test_resource_kind,
                start_time_min=doctor_plan["actual_start_min"],
                service_time_min=turnaround_min,
            )
            if shared_resource_state is None:
                state.resource_status = status
            return {
                "resource_kind": "doctor",
                "slot_index": doctor_plan["slot_index"],
                "wait_min": doctor_plan["wait_min"],
                "service_time_min": doctor_plan["service_time_min"],
                "service_time_source": "test_order",
                "actual_start_min": doctor_plan["actual_start_min"],
                "end_time_min": doctor_plan["end_time_min"],
                "capacity": doctor_plan["capacity"],
                "pending_result_plan": {
                    "resource_kind": test_resource_kind,
                    "slot_index": test_plan["slot_index"],
                    "wait_min": test_plan["wait_min"],
                    "service_time_min": turnaround_min,
                    "service_time_source": turnaround_source,
                    "actual_start_min": test_plan["actual_start_min"],
                    "ready_time_min": test_plan["end_time_min"],
                    "capacity": test_plan["capacity"],
                },
            }
        elif normalized_action in {"consult_before_handoff", "consult_specialty"}:
            resource_kind = "consult"
            service_time_min, service_time_source = self._consult_service_time(case, normalized_target)
        else:
            resource_kind = "doctor"
            service_time_min = self.DEFAULT_SERVICE_TIMES_MIN["doctor"]
            service_time_source = "default_doctor"

        plan = self._allocate_resource(
            status,
            resource_kind,
            start_time_min=start_time_min,
            service_time_min=service_time_min,
        )
        if shared_resource_state is None:
            state.resource_status = status

        return {
            "resource_kind": plan["resource_kind"],
            "slot_index": plan["slot_index"],
            "wait_min": plan["wait_min"],
            "service_time_min": int(service_time_min),
            "service_time_source": service_time_source,
            "actual_start_min": plan["actual_start_min"],
            "end_time_min": plan["end_time_min"],
            "capacity": plan["capacity"],
        }
