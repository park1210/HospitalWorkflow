from __future__ import annotations

from typing import Any


def _first_event_by_action(events: list[dict[str, Any]], action: str) -> dict[str, Any] | None:
    for event in events:
        if str(event.get("action", "")).strip() == action:
            return event
    return None


def _sum_matching(events: list[dict[str, Any]], key: str, *, resource_kind: str | None = None) -> int:
    total = 0
    for event in events:
        if resource_kind and str(event.get("resource_kind", "")).strip() != resource_kind:
            continue
        total += int(event.get(key, 0) or 0)
    return total


def build_temporal_metrics(state_dict: dict[str, Any]) -> dict[str, Any]:
    time_events = list(state_dict.get("time_events", []) or [])
    objective_findings = list(state_dict.get("objective_findings", []) or [])
    queue_wait_time_min = sum(
        int(event.get("minutes_elapsed", 0) or 0)
        for event in time_events
        if str(event.get("action", "")).strip() == "waiting_in_queue"
    )
    care_elapsed_time_min = sum(
        int(event.get("minutes_elapsed", 0) or 0)
        for event in time_events
        if str(event.get("action", "")).strip() != "waiting_in_queue"
    )
    first_test = _first_event_by_action(time_events, "request_test")
    first_handoff = _first_event_by_action(time_events, "make_diagnostic_summary")
    first_stabilization = _first_event_by_action(time_events, "stabilize")

    return {
        "arrival_time_min": int(state_dict.get("arrival_time_min", 0) or 0),
        "queue_wait_time_min": queue_wait_time_min,
        "care_elapsed_time_min": care_elapsed_time_min,
        "total_elapsed_time_min": int(state_dict.get("current_time_min", 0) or 0),
        "time_to_first_objective_step_min": int(first_test.get("end_time_min", -1) or -1) if first_test else None,
        "time_to_handoff_min": int(first_handoff.get("end_time_min", -1) or -1) if first_handoff else None,
        "time_to_stabilization_min": int(first_stabilization.get("end_time_min", -1) or -1) if first_stabilization else None,
        "time_to_final_diagnosis_min": int(state_dict.get("current_time_min", 0) or 0),
        "objective_findings_count": len(objective_findings),
        "deterioration_event_count": len(list(state_dict.get("deterioration_events", []) or [])),
    }


def build_resource_metrics(state_dict: dict[str, Any]) -> dict[str, Any]:
    resource_events = list(state_dict.get("resource_events", []) or [])
    requested_tests = list(state_dict.get("requested_tests", []) or [])
    requested_consults = list(state_dict.get("requested_consults", []) or [])

    return {
        "resource_event_count": len(resource_events),
        "total_wait_time_min": _sum_matching(resource_events, "wait_min"),
        "total_service_time_min": _sum_matching(resource_events, "service_time_min"),
        "doctor_service_time_min": _sum_matching(resource_events, "service_time_min", resource_kind="doctor"),
        "imaging_service_time_min": _sum_matching(resource_events, "service_time_min", resource_kind="imaging"),
        "consult_service_time_min": _sum_matching(resource_events, "service_time_min", resource_kind="consult"),
        "requested_test_count": len(requested_tests),
        "requested_consult_count": len(requested_consults),
    }
