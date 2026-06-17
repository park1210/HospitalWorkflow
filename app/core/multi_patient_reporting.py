from __future__ import annotations

from statistics import mean
from typing import Any


def _count_action(time_events: list[dict[str, Any]], action: str) -> int:
    return sum(1 for event in time_events if str(event.get("action", "")).strip() == action)


def _count_resource_events(resource_events: list[dict[str, Any]], action: str) -> int:
    return sum(1 for event in resource_events if str(event.get("action", "")).strip() == action)


def _case_summary_row(result: dict[str, Any]) -> dict[str, Any]:
    queue_metrics = dict(result.get("queue_metrics", {}) or {})
    reasoning_state = dict(result.get("reasoning_state", {}) or {})
    temporal_metrics = dict(result.get("temporal_metrics", {}) or {})
    resource_metrics = dict(result.get("resource_metrics", {}) or {})
    time_events = list(reasoning_state.get("time_events", []) or [])
    resource_events = list(reasoning_state.get("resource_events", []) or [])
    dynamic_priority = dict(queue_metrics.get("dynamic_priority", {}) or {})

    return {
        "case_id": str(result.get("case_id", "")).strip(),
        "queue_position": int(queue_metrics.get("queue_position", 0) or 0),
        "arrival_time_min": int(queue_metrics.get("arrival_time_min", 0) or 0),
        "scheduler_start_time_min": int(queue_metrics.get("scheduler_start_time_min", 0) or 0),
        "triage_level": int(queue_metrics.get("triage_level", 3) or 3),
        "effective_triage_level": int(dynamic_priority.get("effective_triage_level", queue_metrics.get("triage_level", 3)) or queue_metrics.get("triage_level", 3) or 3),
        "deterioration_risk": str(dynamic_priority.get("deterioration_risk", "low")).strip(),
        "wait_escalation_steps": int(dynamic_priority.get("wait_escalation_steps", 0) or 0),
        "queue_wait_time_min": int(queue_metrics.get("queue_wait_time_min", 0) or 0),
        "care_elapsed_time_min": int(queue_metrics.get("care_elapsed_time_min", 0) or 0),
        "time_to_first_objective_step_min": temporal_metrics.get("time_to_first_objective_step_min"),
        "time_to_handoff_min": temporal_metrics.get("time_to_handoff_min"),
        "time_to_final_diagnosis_min": temporal_metrics.get("time_to_final_diagnosis_min"),
        "predicted_diagnosis": str(result.get("predicted_diagnosis", "")).strip(),
        "predicted_department": str(result.get("predicted_department", "")).strip(),
        "diagnosis_correct": bool(result.get("diagnosis_correct", False)),
        "department_correct": bool(result.get("department_correct", False)),
        "observation_intervals": _count_action(time_events, "observe_patient"),
        "reassessment_count": _count_action(time_events, "perform_assessment"),
        "await_test_result_intervals": _count_action(time_events, "await_test_results"),
        "pending_test_requests": _count_resource_events(resource_events, "pending_test_result"),
        "requested_test_count": int(resource_metrics.get("requested_test_count", 0) or 0),
        "requested_consult_count": int(resource_metrics.get("requested_consult_count", 0) or 0),
        "deterioration_event_count": int(temporal_metrics.get("deterioration_event_count", 0) or 0),
        "episode_reward": float(result.get("episode_reward", 0.0) or 0.0),
    }


def build_multi_patient_report(batch_result: dict[str, Any]) -> dict[str, Any]:
    results = list(batch_result.get("results", []) or [])
    rows = [_case_summary_row(result) for result in results]
    diagnosis_correct_count = sum(1 for row in rows if row["diagnosis_correct"])
    department_correct_count = sum(1 for row in rows if row["department_correct"])

    queue_waits = [int(row["queue_wait_time_min"] or 0) for row in rows]
    observation_rows = [row for row in rows if int(row["observation_intervals"] or 0) > 0]
    reprioritized_rows = [row for row in rows if int(row["wait_escalation_steps"] or 0) > 0]
    pending_wait_rows = [row for row in rows if int(row["await_test_result_intervals"] or 0) > 0]

    return {
        "run_id": str(batch_result.get("run_id", "")).strip(),
        "case_count": len(rows),
        "queue_policy": str(batch_result.get("queue_policy", "")).strip(),
        "summary": {
            "diagnosis_correct_count": diagnosis_correct_count,
            "department_correct_count": department_correct_count,
            "diagnosis_accuracy": round(diagnosis_correct_count / len(rows), 4) if rows else 0.0,
            "department_accuracy": round(department_correct_count / len(rows), 4) if rows else 0.0,
            "average_queue_wait_time_min": round(mean(queue_waits), 2) if queue_waits else 0.0,
            "max_queue_wait_time_min": max(queue_waits) if queue_waits else 0,
            "observation_case_count": len(observation_rows),
            "reprioritized_case_count": len(reprioritized_rows),
            "pending_wait_case_count": len(pending_wait_rows),
        },
        "rows": rows,
    }


def render_multi_patient_report_markdown(report: dict[str, Any]) -> str:
    summary = dict(report.get("summary", {}) or {})
    rows = list(report.get("rows", []) or [])
    lines = [
        f"# Multi-Patient Run Summary ({report.get('run_id', '')})",
        "",
        f"- queue_policy: `{report.get('queue_policy', '')}`",
        f"- case_count: `{report.get('case_count', 0)}`",
        f"- diagnosis_accuracy: `{summary.get('diagnosis_accuracy', 0.0)}`",
        f"- department_accuracy: `{summary.get('department_accuracy', 0.0)}`",
        f"- average_queue_wait_time_min: `{summary.get('average_queue_wait_time_min', 0.0)}`",
        f"- max_queue_wait_time_min: `{summary.get('max_queue_wait_time_min', 0)}`",
        f"- observation_case_count: `{summary.get('observation_case_count', 0)}`",
        f"- reprioritized_case_count: `{summary.get('reprioritized_case_count', 0)}`",
        f"- pending_wait_case_count: `{summary.get('pending_wait_case_count', 0)}`",
        "",
        "| case_id | q_pos | triage | eff_triage | risk | wait | observe | reassess | await | diag | dept | correct |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    for row in rows:
        correct = "diag" if row["diagnosis_correct"] else ""
        if row["department_correct"]:
            correct = f"{correct}+dept" if correct else "dept"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["case_id"]),
                    str(row["queue_position"]),
                    str(row["triage_level"]),
                    str(row["effective_triage_level"]),
                    str(row["deterioration_risk"]),
                    f"{row['queue_wait_time_min']}m",
                    str(row["observation_intervals"]),
                    str(row["reassessment_count"]),
                    str(row["await_test_result_intervals"]),
                    str(row["predicted_diagnosis"]),
                    str(row["predicted_department"]),
                    correct or "none",
                ]
            )
            + " |"
        )

    return "\n".join(lines) + "\n"
