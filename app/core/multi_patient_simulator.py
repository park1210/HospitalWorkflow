from __future__ import annotations

from typing import Any

from app.core.queue_manager import QueueManager
from app.core.simulator import run_single_case


class MultiPatientERSimulator:
    def __init__(self) -> None:
        self.queue_manager = QueueManager()

    @staticmethod
    def _doctor_next_available_min(shared_resource_state: dict[str, Any]) -> int:
        doctor_state = dict(shared_resource_state.get("doctor", {}) or {})
        next_available_times = list(doctor_state.get("next_available_times", []) or [])
        if not next_available_times:
            return 0
        return min(int(value or 0) for value in next_available_times)

    def run_batch(
        self,
        cases: list[dict[str, Any]],
        run_id: str,
        max_turns: int,
        live_runtime: Any | None = None,
    ) -> dict[str, Any]:
        queue = self.queue_manager.build_priority_queue(cases)
        results: list[dict[str, Any]] = []
        shared_resource_state: dict[str, Any] = {}
        selection_order = 0

        if live_runtime is not None and hasattr(live_runtime, "initialize"):
            live_runtime.initialize(queue)

        while queue:
            doctor_next_available_min = self._doctor_next_available_min(shared_resource_state)
            queued_case, queue, selection_time_min, dynamic_priority = self.queue_manager.select_next_case(
                queue,
                doctor_next_available_min,
            )
            selection_order += 1
            case = dict(queued_case.get("case", {}) or {})
            arrival_time_min = int(queued_case.get("arrival_time_min", 0) or 0)
            active_start_time_min = max(doctor_next_available_min, selection_time_min, arrival_time_min)
            queue_context = {
                "queue_position": selection_order,
                "arrival_index": int(queued_case.get("arrival_index", 0) or 0),
                "arrival_time_min": arrival_time_min,
                "triage_level": int(queued_case.get("triage_level", 3) or 3),
                "is_unstable": bool(queued_case.get("is_unstable", False)),
                "needs_resuscitation_now": bool(queued_case.get("needs_resuscitation_now", False)),
                "triage_rationale": str(queued_case.get("triage_rationale", "")).strip(),
                "scheduler_start_time_min": active_start_time_min,
                "dynamic_priority": dynamic_priority,
            }
            if live_runtime is not None and hasattr(live_runtime, "on_case_selected"):
                live_runtime.on_case_selected(
                    queued_case,
                    queue,
                    selection_order=selection_order,
                    active_start_time_min=active_start_time_min,
                    dynamic_priority=dynamic_priority,
                )
            result = run_single_case(
                case,
                run_id,
                max_turns,
                initial_time_offset_min=active_start_time_min,
                shared_resource_state=shared_resource_state,
                live_observer=(live_runtime.on_update if live_runtime is not None and hasattr(live_runtime, "on_update") else None),
                queue_context=queue_context,
            )
            temporal_metrics = dict(result.get("temporal_metrics", {}) or {})
            care_elapsed_time_min = int(temporal_metrics.get("care_elapsed_time_min", 0) or 0)
            queue_wait_time_min = int(temporal_metrics.get("queue_wait_time_min", 0) or 0)
            result["queue_metrics"] = {
                **queue_context,
                "queue_wait_time_min": queue_wait_time_min,
                "care_elapsed_time_min": care_elapsed_time_min,
            }
            results.append(result)

        if live_runtime is not None and hasattr(live_runtime, "finalize"):
            live_runtime.finalize()

        return {
            "run_id": run_id,
            "case_count": len(results),
            "queue_policy": "time_aware_triage_priority_with_wait_based_reprioritization",
            "results": results,
        }
