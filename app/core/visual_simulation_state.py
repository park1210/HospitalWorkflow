from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from app.config import settings


ZONE_ORDER = [
    "waiting_room",
    "er_workup",
    "observation",
    "awaiting_results",
    "specialty_review",
    "completed",
]


def _load_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _result_path(run_id: str, case_id: str) -> Path:
    return settings.RESULTS_DIR / run_id / f"{case_id}_result.json"


def _event_times(time_events: list[dict[str, Any]]) -> list[int]:
    times: set[int] = set()
    for event in time_events:
        times.add(int(event.get("start_time_min", 0) or 0))
        times.add(int(event.get("end_time_min", 0) or 0))
    return sorted(times)


def _classify_zone(detail: dict[str, Any], minute: int) -> str:
    queue_metrics = dict(detail.get("queue_metrics", {}) or {})
    time_events = list(detail.get("time_events", []) or [])
    scheduler_start = int(queue_metrics.get("scheduler_start_time_min", 0) or 0)

    if minute < scheduler_start:
        return "waiting_room"

    latest_event: dict[str, Any] | None = None
    for event in time_events:
        start = int(event.get("start_time_min", 0) or 0)
        end = int(event.get("end_time_min", 0) or 0)
        if start <= minute <= end:
            latest_event = event
        elif end <= minute:
            latest_event = event

    if latest_event is None:
        return "waiting_room"

    action = str(latest_event.get("action", "")).strip()
    actor = str(latest_event.get("actor", "")).strip()
    end_time = int(latest_event.get("end_time_min", 0) or 0)

    if minute >= end_time and action == "diagnose":
        return "completed"
    if action in {"await_test_results"}:
        return "awaiting_results"
    if action in {"observe_patient"}:
        return "observation"
    if actor == "er_department":
        return "er_workup"
    if actor not in {"system", "er_department"}:
        return "specialty_review"
    return "er_workup"


def _patient_alerts(detail: dict[str, Any], minute: int) -> list[str]:
    alerts: list[str] = []
    queue_metrics = dict(detail.get("queue_metrics", {}) or {})
    if int(queue_metrics.get("wait_escalation_steps", 0) or 0) > 0:
        alerts.append("reprioritized")
    if list(detail.get("pending_results", []) or []):
        alerts.append("pending_result")
    deterioration_events = list(detail.get("deterioration_events", []) or [])
    if any(int(event.get("minute", 0) or 0) <= minute for event in deterioration_events):
        alerts.append("deterioration")
    observation_status = str(detail.get("observation_status", "")).strip().lower()
    if observation_status in {"under_observation", "reassessment_due", "completed"}:
        alerts.append("observation")
    return alerts


def _patient_snapshot(detail: dict[str, Any], minute: int) -> dict[str, Any]:
    queue_metrics = dict(detail.get("queue_metrics", {}) or {})
    return {
        "case_id": str(detail.get("case_id", "")).strip(),
        "zone": _classify_zone(detail, minute),
        "triage_level": int(queue_metrics.get("triage_level", 3) or 3),
        "effective_triage_level": int(
            (queue_metrics.get("dynamic_priority", {}) or {}).get(
                "effective_triage_level",
                queue_metrics.get("triage_level", 3),
            )
            or queue_metrics.get("triage_level", 3)
            or 3
        ),
        "predicted_diagnosis": str(detail.get("predicted_diagnosis", "")).strip(),
        "predicted_department": str(detail.get("predicted_department", "")).strip(),
        "diagnosis_correct": bool(detail.get("diagnosis_correct", False)),
        "department_correct": bool(detail.get("department_correct", False)),
        "alerts": _patient_alerts(detail, minute),
    }


def _resource_occupancy(details: list[dict[str, Any]], minute: int) -> list[dict[str, Any]]:
    occupancy: list[dict[str, Any]] = []
    for detail in details:
        for event in list(detail.get("resource_events", []) or []):
            start = int(event.get("actual_start_min", 0) or 0)
            end = int(event.get("end_time_min", 0) or 0)
            if start <= minute < end:
                occupancy.append(
                    {
                        "case_id": str(detail.get("case_id", "")).strip(),
                        "resource_kind": str(event.get("resource_kind", "")).strip(),
                        "action": str(event.get("action", "")).strip(),
                        "target": str(event.get("target", "")).strip(),
                        "start_time_min": start,
                        "end_time_min": end,
                    }
                )
    return occupancy


def _run_frames(details: list[dict[str, Any]]) -> list[dict[str, Any]]:
    minutes: set[int] = set()
    for detail in details:
        for minute in _event_times(list(detail.get("time_events", []) or [])):
            minutes.add(minute)
    ordered_minutes = sorted(minutes)

    frames: list[dict[str, Any]] = []
    for minute in ordered_minutes:
        patients = [_patient_snapshot(detail, minute) for detail in details]
        frames.append(
            {
                "minute": minute,
                "zones": {
                    zone: [patient for patient in patients if patient["zone"] == zone]
                    for zone in ZONE_ORDER
                },
                "resource_occupancy": _resource_occupancy(details, minute),
            }
        )
    return frames


def load_case_details_for_run(run_id: str, report: dict[str, Any]) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for row in list(report.get("rows", []) or []):
        case_id = str(row.get("case_id", "")).strip()
        if not case_id:
            continue
        result_path = _result_path(run_id, case_id)
        if not result_path.exists():
            continue
        result = _load_json(result_path)
        reasoning_state = dict(result.get("reasoning_state", {}) or {})
        details.append(
            {
                "case_id": case_id,
                "predicted_diagnosis": str(result.get("predicted_diagnosis", "")).strip(),
                "predicted_department": str(result.get("predicted_department", "")).strip(),
                "ground_truth": str(result.get("ground_truth", "")).strip(),
                "ground_truth_department": str(result.get("ground_truth_department", "")).strip(),
                "diagnosis_correct": bool(result.get("diagnosis_correct", False)),
                "department_correct": bool(result.get("department_correct", False)),
                "queue_metrics": dict(result.get("queue_metrics", {}) or {}),
                "temporal_metrics": dict(result.get("temporal_metrics", {}) or {}),
                "resource_metrics": dict(result.get("resource_metrics", {}) or {}),
                "time_events": list(reasoning_state.get("time_events", []) or []),
                "resource_events": list(reasoning_state.get("resource_events", []) or []),
                "deterioration_events": list(reasoning_state.get("deterioration_events", []) or []),
                "pending_results": list(reasoning_state.get("pending_results", []) or []),
                "observation_status": str(reasoning_state.get("observation_status", "")).strip(),
                "next_reassessment_time_min": reasoning_state.get("next_reassessment_time_min"),
            }
        )
    return details


def build_visual_simulation_state(run_id: str) -> dict[str, Any]:
    report_path = settings.REPORTS_DIR / run_id / "multi_patient_run_summary.json"
    report = _load_json(report_path)
    details = load_case_details_for_run(run_id, report)
    frames = _run_frames(details)
    return {
        "run_id": run_id,
        "queue_policy": str(report.get("queue_policy", "")).strip(),
        "summary": dict(report.get("summary", {}) or {}),
        "zones": ZONE_ORDER,
        "patients": [
            {
                "case_id": str(detail.get("case_id", "")).strip(),
                "predicted_diagnosis": str(detail.get("predicted_diagnosis", "")).strip(),
                "predicted_department": str(detail.get("predicted_department", "")).strip(),
                "ground_truth": str(detail.get("ground_truth", "")).strip(),
                "ground_truth_department": str(detail.get("ground_truth_department", "")).strip(),
                "queue_metrics": dict(detail.get("queue_metrics", {}) or {}),
                "temporal_metrics": dict(detail.get("temporal_metrics", {}) or {}),
                "resource_metrics": dict(detail.get("resource_metrics", {}) or {}),
            }
            for detail in details
        ],
        "frames": frames,
    }
