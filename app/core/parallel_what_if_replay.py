from __future__ import annotations

import json
import re
from functools import lru_cache
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.config import settings
from app.core.hospital_parallel_scheduler import HospitalParallelScheduler
from app.core.hospital_scheduler_state import HospitalSchedulerState
from app.data.loader import load_processed_cases, load_raw_cases
from app.data.transform import transform_case


def _report_path(run_id: str) -> Path:
    return settings.REPORTS_DIR / str(run_id).strip() / "parallel_live_run_summary.json"


def _load_parallel_report(run_id: str) -> dict[str, Any]:
    path = _report_path(run_id)
    if not path.exists():
        raise FileNotFoundError(f"Parallel run summary not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _dataset_case_map() -> dict[str, dict[str, Any]]:
    if settings.USE_PROCESSED_CASES and settings.PROCESSED_DATA_PATH.exists():
        cases = load_processed_cases(settings.PROCESSED_DATA_PATH)
    else:
        raw_cases = load_raw_cases(settings.RAW_DATA_PATH)
        cases = [transform_case(case, idx) for idx, case in enumerate(raw_cases)]
    return {
        str(case.get("case_id", "")).strip(): dict(case)
        for case in cases
        if str(case.get("case_id", "")).strip()
    }


def _case_data_map_for_report(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    source_cases = [dict(item or {}) for item in list(report.get("source_cases", []) or []) if dict(item or {})]
    if source_cases:
        return {
            str(case.get("case_id", "")).strip(): dict(case)
            for case in source_cases
            if str(case.get("case_id", "")).strip()
        }
    return _dataset_case_map()


def _case_detail(run_id: str, case_id: str) -> dict[str, Any]:
    snapshot_path = settings.REPORTS_DIR / str(run_id).strip() / "live_visual_state.json"
    if not snapshot_path.exists():
        return {}
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    return dict(dict(snapshot.get("case_details", {}) or {}).get(str(case_id).strip(), {}) or {})


def _original_summary(runtime: dict[str, Any]) -> dict[str, Any]:
    return {
        "diagnosis": str(runtime.get("assessment_summary", "")).strip(),
        "department": str(runtime.get("target_department", "")).strip(),
        "diagnosis_correct": False,
        "department_correct": False,
        "episode_reward": 0.0,
    }


def _snapshot_minute(snapshot_id: str) -> int | None:
    match = re.search(r"_m(\d+)$", str(snapshot_id).strip())
    if not match:
        return None
    return int(match.group(1))


def _scheduler_snapshots(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(item or {}) for item in list(report.get("snapshots", []) or []) if dict(item or {})]


def _scheduler_snapshot_for_case(report: dict[str, Any], snapshot_id: str, case_id: str) -> dict[str, Any]:
    snapshots = _scheduler_snapshots(report)
    if not snapshots:
        return dict(report.get("final_state", {}) or {})
    target_minute = _snapshot_minute(snapshot_id)
    normalized_case_id = str(case_id).strip()
    candidates = [
        snapshot
        for snapshot in snapshots
        if normalized_case_id in dict(snapshot.get("cases", {}) or {})
    ]
    if not candidates:
        return dict(report.get("final_state", {}) or {})
    if target_minute is None:
        return dict(candidates[-1] or {})
    exact = [
        snapshot
        for snapshot in candidates
        if int(snapshot.get("current_minute", -1) or -1) == target_minute
    ]
    if exact:
        return dict(exact[-1] or {})
    earlier = [
        snapshot
        for snapshot in candidates
        if int(snapshot.get("current_minute", -1) or -1) <= target_minute
    ]
    if earlier:
        return dict(earlier[-1] or {})
    return dict(candidates[0] or {})


def _runtime_from_scheduler_snapshot(snapshot: dict[str, Any], case_id: str) -> dict[str, Any]:
    return dict(dict(snapshot.get("cases", {}) or {}).get(str(case_id).strip(), {}) or {})


def _decision_snapshot(runtime: dict[str, Any], snapshot_id: str) -> dict[str, Any]:
    for item in list(runtime.get("decision_snapshots", []) or []):
        item_dict = dict(item or {})
        if str(item_dict.get("snapshot_id", "")).strip() == str(snapshot_id).strip():
            return item_dict
    return {}


def _default_snapshot(snapshot_id: str, case_id: str, scheduler_snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "snapshot_id": str(snapshot_id).strip(),
        "case_id": str(case_id).strip(),
        "node": "parallel_scheduler_decision",
        "turn_index": int(
            dict(dict(scheduler_snapshot.get("cases", {}) or {}).get(str(case_id).strip(), {}) or {}).get("er_turn_count", 0) or 0
        ),
        "current_minute": int(scheduler_snapshot.get("current_minute", 0) or 0),
    }


def _normalize_action(selected_action: dict[str, Any]) -> dict[str, str]:
    return {
        "type": str(selected_action.get("type", "")).strip(),
        "target": str(selected_action.get("target", "")).strip(),
    }


def _replay_questions(detail: dict[str, Any], selected_action: dict[str, Any]) -> list[dict[str, str]]:
    questions = [dict(item or {}) for item in list(detail.get("questions", []) or [])]
    action_type = str(selected_action.get("type", "")).strip()
    target = str(selected_action.get("target", "")).strip()
    if action_type == "ask_patient":
        questions.append(
            {
                "question": target or "Can you describe what feels most different right now?",
                "answer": "The patient clarifies the symptom pattern without introducing a major new contradiction.",
            }
        )
    return questions[-6:]


def _replay_tests(detail: dict[str, Any], selected_action: dict[str, Any]) -> list[str]:
    tests = [str(item).strip() for item in list(detail.get("tests", []) or []) if str(item).strip()]
    action_type = str(selected_action.get("type", "")).strip()
    target = str(selected_action.get("target", "")).strip()
    if action_type == "request_test" and target and target not in tests:
        tests.append(target)
    if action_type == "await_results" and target and target not in tests:
        tests.append(target)
    return tests[-6:]


def _replay_findings(detail: dict[str, Any], selected_action: dict[str, Any], runtime: dict[str, Any]) -> list[str]:
    findings = [str(item).strip() for item in list(detail.get("objective_findings", []) or []) if str(item).strip()]
    action_type = str(selected_action.get("type", "")).strip()
    target = str(selected_action.get("target", "")).strip()
    suspected = str(runtime.get("assessment_summary", "")).strip() or "the working problem"
    if action_type == "request_test" and target:
        findings.append(f"{target} added another objective clue supporting {suspected}.")
    if action_type == "await_results" and target:
        findings.append(f"Waiting for {target} delayed escalation while the same working diagnosis stayed in play.")
    if action_type in {"consult_specialty", "request_consult"}:
        department = str(selected_action.get("target", "")).strip() or str(runtime.get("target_department", "")).strip()
        findings.append(f"{department} specialty review tightened ownership around the leading diagnosis.")
    deduped: list[str] = []
    for item in findings:
        if item and item not in deduped:
            deduped.append(item)
    return deduped[-8:]


def _replay_department(runtime: dict[str, Any], selected_action: dict[str, Any]) -> str:
    action_type = str(selected_action.get("type", "")).strip()
    target = str(selected_action.get("target", "")).strip()
    if action_type in {"consult_specialty", "request_consult"} and target:
        return target
    return str(runtime.get("target_department", "")).strip()


def _replay_reward(detail: dict[str, Any], selected_action: dict[str, Any]) -> float:
    action_type = str(selected_action.get("type", "")).strip()
    if action_type == "ask_patient":
        return -0.1
    if action_type == "request_test":
        return 0.15 if not list(detail.get("objective_findings", []) or []) else -0.05
    if action_type == "await_results":
        return -0.2
    if action_type in {"consult_specialty", "request_consult"}:
        return 0.2
    if action_type == "diagnose":
        return 0.1 if list(detail.get("objective_findings", []) or []) else -0.2
    return 0.0


def _replay_zone(detail: dict[str, Any], selected_action: dict[str, Any]) -> str:
    action_type = str(selected_action.get("type", "")).strip()
    if action_type == "request_test":
        return "awaiting_results"
    if action_type == "await_results":
        return "awaiting_results"
    if action_type in {"consult_specialty", "request_consult"}:
        return "specialty_review"
    if action_type == "diagnose":
        return "completed"
    return str(detail.get("zone", "")).strip() or "er_workup"


def _trajectory_steps(
    *,
    runtime: dict[str, Any],
    detail: dict[str, Any],
    selected_action: dict[str, Any],
    replay_questions: list[dict[str, str]],
    replay_tests: list[str],
    replay_findings: list[str],
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    action_type = str(selected_action.get("type", "")).strip()
    target = str(selected_action.get("target", "")).strip()
    current_zone = str(detail.get("zone", "")).strip() or "er_workup"

    if action_type == "ask_patient":
        qa = replay_questions[-1] if replay_questions else {}
        steps.append(
            {
                "action": "ask_patient",
                "target": target or "focused_history",
                "zone": current_zone,
                "rationale": "The branch asks one more targeted history question before escalating further.",
                "outcome": {
                    "question": str(qa.get("question", "")).strip(),
                    "answer": str(qa.get("answer", "")).strip(),
                },
            }
        )
    elif action_type == "request_test":
        steps.append(
            {
                "action": "request_test",
                "target": target,
                "zone": "awaiting_results",
                "rationale": "The branch requests another objective test and temporarily frees active ER attention.",
                "outcome": {
                    "tests": replay_tests,
                    "finding": replay_findings[-1] if replay_findings else "",
                },
            }
        )
        steps.append(
            {
                "action": "review_results",
                "target": target,
                "zone": "er_workup",
                "rationale": "After the result returns, the case re-enters the ER decision queue.",
                "outcome": {
                    "objective_findings": replay_findings,
                },
            }
        )
    elif action_type == "await_results":
        steps.append(
            {
                "action": "await_results",
                "target": target,
                "zone": "awaiting_results",
                "rationale": "The branch waits for the pending objective result before escalating to specialty.",
                "outcome": {
                    "tests": replay_tests,
                    "delayed_test": target,
                },
            }
        )
        steps.append(
            {
                "action": "review_results",
                "target": target,
                "zone": "er_workup",
                "rationale": "After the pending result returns, ER reassesses the case from the bedside.",
                "outcome": {
                    "objective_findings": replay_findings,
                },
            }
        )
    elif action_type in {"consult_specialty", "request_consult"}:
        department = target or str(runtime.get("target_department", "")).strip()
        steps.append(
            {
                "action": "request_specialty",
                "target": department,
                "zone": "er_workup",
                "rationale": "The branch escalates ownership to the leading specialty.",
                "outcome": {
                    "department": department,
                },
            }
        )
        steps.append(
            {
                "action": "specialty_consult",
                "target": department,
                "zone": "specialty_review",
                "rationale": "The specialty doctor reaches the consult room and performs focused review.",
                "outcome": {
                    "consult_note": f"{department} reviewed the current ER evidence and tightened the differential.",
                },
            }
        )
    elif action_type == "diagnose":
        steps.append(
            {
                "action": "diagnose",
                "target": target or str(runtime.get("assessment_summary", "")).strip(),
                "zone": "completed",
                "rationale": "The branch finalizes immediately based on currently available evidence.",
                "outcome": {
                    "diagnosis": str(runtime.get("assessment_summary", "")).strip(),
                },
            }
        )
    return steps


def _event_window(report: dict[str, Any], case_id: str, snapshot_minute: int | None, window: int = 3) -> list[dict[str, Any]]:
    events = [
        dict(item or {})
        for item in list(dict(report.get("final_state", {}) or {}).get("event_log", []) or [])
        if str(dict(item or {}).get("case_id", "")).strip() == str(case_id).strip()
    ]
    if snapshot_minute is None:
        return events[-6:]
    filtered = [
        item
        for item in events
        if abs(int(item.get("minute", 0) or 0) - int(snapshot_minute or 0)) <= int(window or 0)
    ]
    return filtered[-8:]


def _reconstruct_state(snapshot: dict[str, Any], report: dict[str, Any]) -> HospitalSchedulerState:
    case_ids = [str(case_id).strip() for case_id in list(dict(snapshot.get("cases", {}) or {}).keys()) if str(case_id).strip()]
    all_cases = _case_data_map_for_report(report)
    case_data_map = {case_id: dict(all_cases.get(case_id, {}) or {}) for case_id in case_ids}
    return HospitalSchedulerState.from_snapshot(snapshot, case_data_map=case_data_map)


def _branch_event_delta(state_before: HospitalSchedulerState, state_after: HospitalSchedulerState, case_id: str) -> list[dict[str, Any]]:
    before_count = len(list(state_before.event_log or []))
    case_events = [
        dict(item or {})
        for item in list(state_after.event_log or [])[before_count:]
        if str(dict(item or {}).get("case_id", "")).strip() == str(case_id).strip()
    ]
    return case_events


def _events_to_trajectory_steps(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for event in events:
        payload = dict(event.get("payload", {}) or {})
        steps.append(
            {
                "action": str(event.get("action", "")).strip(),
                "target": str(payload.get("requested_test", "")).strip() or str(payload.get("department", "")).strip(),
                "zone": str(event.get("zone", "")).strip() or str(dict(event.get("state_delta", {}) or {}).get("zone", "")).strip(),
                "rationale": str(event.get("rationale", "")).strip(),
                "outcome": payload,
                "minute": int(event.get("minute", 0) or 0),
                "event_type": str(event.get("event_type", "")).strip(),
            }
        )
    return steps


def replay_parallel_case_from_snapshot(
    *,
    run_id: str,
    case_id: str,
    snapshot_id: str,
    selected_action: dict[str, Any],
) -> dict[str, Any]:
    report = _load_parallel_report(run_id)
    normalized_case_id = str(case_id).strip()
    normalized_action = _normalize_action(selected_action)
    detail = _case_detail(run_id, normalized_case_id)

    scheduler_snapshot = _scheduler_snapshot_for_case(report, snapshot_id, normalized_case_id)
    branch_state = _reconstruct_state(scheduler_snapshot, report)
    state_before = deepcopy(branch_state)
    runtime_before = branch_state.case(normalized_case_id).to_summary()
    scheduler_decision = _decision_snapshot(runtime_before, snapshot_id)

    original = _original_summary(runtime_before)
    scheduler = HospitalParallelScheduler()
    scheduler.apply_branch_action(
        branch_state,
        case_id=normalized_case_id,
        selected_action=normalized_action,
    )
    scheduler.run_branch_until_stable(
        branch_state,
        case_id=normalized_case_id,
        minute_horizon=12,
    )

    runtime_after = branch_state.case(normalized_case_id).to_summary()
    replay_questions = [dict(item or {}) for item in list(runtime_after.get("question_history", []) or [])][-6:]
    replay_tests = [str(item).strip() for item in list(runtime_after.get("recommended_tests", []) or []) if str(item).strip()][-6:]
    replay_findings = [str(item).strip() for item in list(runtime_after.get("objective_findings", []) or []) if str(item).strip()][-8:]
    branch_events = _branch_event_delta(state_before, branch_state, normalized_case_id)
    trajectory_steps = _events_to_trajectory_steps(branch_events) or _trajectory_steps(
        runtime=runtime_before,
        detail=detail,
        selected_action=normalized_action,
        replay_questions=replay_questions,
        replay_tests=replay_tests,
        replay_findings=replay_findings,
    )
    replay_department = str(runtime_after.get("target_department", "")).strip() or _replay_department(runtime_before, normalized_action)
    reward_delta = _replay_reward(detail, normalized_action)
    replay_result = {
        "case_id": normalized_case_id,
        "predicted_diagnosis": str(runtime_after.get("assessment_summary", "")).strip() or str(runtime_before.get("assessment_summary", "")).strip(),
        "predicted_department": replay_department,
        "final_decision_source": "parallel_what_if_branch",
        "diagnosis_correct": False,
        "department_correct": False,
        "episode_reward": float(original.get("episode_reward", 0.0) or 0.0) + reward_delta,
        "objective_findings": replay_findings,
        "questions": replay_questions,
        "tests": replay_tests,
        "trajectory_steps": trajectory_steps,
        "turn_count": int(runtime_after.get("er_turn_count", runtime_before.get("er_turn_count", 0)) or 0) + max(1, len(branch_events)),
        "zone": str(runtime_after.get("zone", "")).strip() or _replay_zone(detail, normalized_action),
    }
    comparison = {
        "snapshot_id": str(snapshot_id).strip(),
        "case_id": normalized_case_id,
        "node": "parallel_scheduler_decision",
        "turn_index": int(runtime_before.get("er_turn_count", 0) or 0),
        "selected_action": normalized_action,
        "original": original,
        "replay": {
            "diagnosis": str(replay_result.get("predicted_diagnosis", "")).strip(),
            "department": str(replay_result.get("predicted_department", "")).strip(),
            "diagnosis_correct": False,
            "department_correct": False,
            "episode_reward": float(replay_result.get("episode_reward", 0.0) or 0.0),
        },
        "reward_delta": round(reward_delta, 4),
        "improved": bool(reward_delta > 0.0),
        "timeline": {
            "original_events": _event_window(report, normalized_case_id, _snapshot_minute(snapshot_id)),
            "replay_steps": trajectory_steps,
            "branch_events": branch_events,
        },
    }
    branch_snapshot = _default_snapshot(snapshot_id, normalized_case_id, scheduler_snapshot)
    branch_snapshot["scheduler_context"] = {
        "current_minute": int(branch_state.current_minute or 0),
        "tick": int(branch_state.tick or 0),
        "queues_before": deepcopy(dict(scheduler_snapshot.get("queues", {}) or {})),
        "queues_after": deepcopy(branch_state.queue_snapshot()),
        "resources_before": deepcopy(dict(scheduler_snapshot.get("resources", {}) or {})),
        "resources_after": deepcopy(branch_state.resources.snapshot()),
        "case_before": deepcopy(runtime_before),
        "case_after": deepcopy(runtime_after),
        "decision_snapshot": deepcopy(scheduler_decision),
    }
    return {
        "status": "completed",
        "replay_run_id": f"parallel_{run_id}",
        "snapshot_id": str(snapshot_id).strip(),
        "selected_action": normalized_action,
        "comparison": comparison,
        "replay_result": replay_result,
        "snapshot": branch_snapshot,
    }
