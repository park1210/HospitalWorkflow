from __future__ import annotations

from typing import Any

from app.modules.triage_module import TriageModule


class QueueManager:
    def __init__(self) -> None:
        self.triage_module = TriageModule()

    @staticmethod
    def _deterioration_risk(case: dict[str, Any]) -> str:
        temporal_profile = case.get("temporal_profile", {})
        if not isinstance(temporal_profile, dict):
            return ""
        deterioration_model = temporal_profile.get("deterioration_model", {})
        if not isinstance(deterioration_model, dict):
            return ""
        return str(deterioration_model.get("baseline_risk", "")).strip().lower()

    @staticmethod
    def _wait_escalation_threshold(risk: str) -> int:
        if risk == "high":
            return 10
        if risk == "moderate":
            return 20
        return 40

    def _dynamic_priority(self, item: dict[str, Any], selection_time_min: int) -> dict[str, Any]:
        base_triage = int(item.get("triage_level", 3) or 3)
        arrival_time_min = int(item.get("arrival_time_min", 0) or 0)
        waited_min = max(0, int(selection_time_min or 0) - arrival_time_min)
        risk = str(item.get("deterioration_risk", "")).strip().lower()
        threshold = self._wait_escalation_threshold(risk)
        escalation_steps = 0
        if threshold > 0:
            escalation_steps = waited_min // threshold
        effective_triage = max(1, base_triage - escalation_steps)
        return {
            "base_triage_level": base_triage,
            "effective_triage_level": effective_triage,
            "waited_min": waited_min,
            "deterioration_risk": risk or "low",
            "wait_escalation_steps": escalation_steps,
            "wait_escalation_threshold_min": threshold,
        }

    def _arrival_time_min(self, case: dict[str, Any], arrival_index: int) -> int:
        temporal_profile = case.get("temporal_profile", {})
        if isinstance(temporal_profile, dict):
            temporal_arrival = temporal_profile.get("arrival_time_min")
            if temporal_arrival is not None:
                return int(temporal_arrival or 0)
        return int(case.get("arrival_time_min", arrival_index * 5) or 0)

    def _priority_sort_key(self, item: dict[str, Any], selection_time_min: int | None = None) -> tuple[int, int, int, int, int]:
        effective = self._dynamic_priority(item, int(selection_time_min or item.get("arrival_time_min", 0) or 0))
        return (
            int(effective.get("effective_triage_level", item.get("triage_level", 3)) or item.get("triage_level", 3) or 3),
            0 if bool(item.get("needs_resuscitation_now", False)) else 1,
            -int(effective.get("waited_min", 0) or 0),
            int(item.get("arrival_time_min", 0) or 0),
            int(item.get("arrival_index", 0) or 0),
        )

    def build_priority_queue(self, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
        queued: list[dict[str, Any]] = []
        for arrival_index, case in enumerate(cases):
            triage_result = self.triage_module.run(case)
            queued.append(
                {
                    "case": case,
                    "arrival_index": arrival_index,
                    "triage_level": int(triage_result.get("triage_level", 3) or 3),
                    "is_unstable": bool(triage_result.get("is_unstable", False)),
                    "needs_resuscitation_now": bool(triage_result.get("needs_resuscitation_now", False)),
                    "triage_rationale": str(triage_result.get("triage_rationale", "")).strip(),
                    "arrival_time_min": self._arrival_time_min(case, arrival_index),
                    "deterioration_risk": self._deterioration_risk(case),
                }
            )

        queued.sort(key=lambda item: self._priority_sort_key(item))
        return queued

    def select_next_case(
        self,
        queued_cases: list[dict[str, Any]],
        current_time_min: int,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], int, dict[str, Any]]:
        if not queued_cases:
            raise ValueError("queued_cases must not be empty")

        ready_cases = [
            item for item in queued_cases if int(item.get("arrival_time_min", 0) or 0) <= int(current_time_min or 0)
        ]
        selection_time_min = int(current_time_min or 0)
        if not ready_cases:
            selection_time_min = min(int(item.get("arrival_time_min", 0) or 0) for item in queued_cases)
            ready_cases = [
                item
                for item in queued_cases
                if int(item.get("arrival_time_min", 0) or 0) <= selection_time_min
            ]

        ordered_ready = sorted(ready_cases, key=lambda item: self._priority_sort_key(item, selection_time_min))
        selected = ordered_ready[0]
        remaining = [item for item in queued_cases if item is not selected]
        dynamic_priority = self._dynamic_priority(selected, selection_time_min)
        return selected, remaining, selection_time_min, dynamic_priority
