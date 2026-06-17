from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import settings
from app.core.logger import create_run_id, save_what_if_comparison, save_what_if_replay
from app.core.parallel_what_if_replay import replay_parallel_case_from_snapshot
from app.core.what_if_replay import get_snapshot_by_id, replay_case_from_snapshot
from app.data.loader import load_processed_cases, load_raw_cases
from app.data.transform import transform_case


@lru_cache(maxsize=1)
def _load_cases() -> list[dict[str, Any]]:
    if settings.USE_PROCESSED_CASES and settings.PROCESSED_DATA_PATH.exists():
        return load_processed_cases(settings.PROCESSED_DATA_PATH)
    raw_cases = load_raw_cases(settings.RAW_DATA_PATH)
    return [transform_case(case, idx) for idx, case in enumerate(raw_cases)]


def _get_case_by_case_id(case_id: str) -> dict[str, Any]:
    normalized = str(case_id).strip()
    for case in _load_cases():
        if str(case.get("case_id", "")).strip() == normalized:
            return dict(case)
    raise KeyError(f"Case not found in dataset: {normalized}")


def _load_result(run_id: str, case_id: str) -> dict[str, Any]:
    result_path = settings.RESULTS_DIR / str(run_id).strip() / f"{str(case_id).strip()}_result.json"
    if not result_path.exists():
        raise FileNotFoundError(f"Result file not found: {result_path}")
    return json.loads(result_path.read_text(encoding="utf-8"))


def _extract_replay_payload(replay_result: dict[str, Any]) -> dict[str, Any]:
    reasoning_state = dict(replay_result.get("reasoning_state", {}) or {})
    trajectory_steps = list(replay_result.get("trajectory_steps", []) or [])
    questions: list[dict[str, str]] = []
    tests: list[str] = []
    for step in trajectory_steps:
        step_data = dict(step or {})
        action = str(step_data.get("action", "")).strip()
        target = str(step_data.get("target", "")).strip()
        outcome = dict(step_data.get("outcome", {}) or {})
        if action == "ask_patient":
            question = str(outcome.get("question", "")).strip()
            answer = str(outcome.get("answer", "")).strip()
            if question or answer:
                questions.append({"question": question, "answer": answer})
        if action == "request_test" and target and target not in tests:
            tests.append(target)
    return {
        "case_id": str(replay_result.get("case_id", "")).strip(),
        "predicted_diagnosis": str(replay_result.get("predicted_diagnosis", "")).strip(),
        "predicted_department": str(replay_result.get("predicted_department", "")).strip(),
        "final_decision_source": str(replay_result.get("final_decision_source", "")).strip(),
        "diagnosis_correct": bool(replay_result.get("diagnosis_correct", False)),
        "department_correct": bool(replay_result.get("department_correct", False)),
        "episode_reward": float(replay_result.get("episode_reward", 0.0) or 0.0),
        "objective_findings": list(reasoning_state.get("objective_findings", []) or []),
        "questions": questions,
        "tests": tests,
        "trajectory_steps": trajectory_steps,
        "turn_count": int(replay_result.get("turn_count", 0) or 0),
    }


def run_case_replay(
    *,
    run_id: str,
    case_id: str,
    snapshot_id: str,
    selected_action: dict[str, Any],
    max_turns: int | None = None,
) -> dict[str, Any]:
    try:
        original_result = _load_result(run_id, case_id)
    except FileNotFoundError:
        return replay_parallel_case_from_snapshot(
            run_id=run_id,
            case_id=case_id,
            snapshot_id=snapshot_id,
            selected_action=selected_action,
        )
    snapshot = get_snapshot_by_id(original_result, snapshot_id)
    case = _get_case_by_case_id(case_id)
    replay_run_id = create_run_id()
    replay_result = replay_case_from_snapshot(
        case=case,
        original_result=original_result,
        snapshot=snapshot,
        selected_action={
            "type": str(selected_action.get("type", "")).strip(),
            "target": str(selected_action.get("target", "")).strip(),
        },
        run_id=replay_run_id,
        max_turns=int(max_turns or settings.MAX_TURNS),
    )
    comparison = dict(replay_result.get("what_if_replay", {}).get("comparison", {}) or {})
    save_what_if_replay(str(case_id).strip(), replay_result, replay_run_id)
    save_what_if_comparison(str(case_id).strip(), comparison, replay_run_id)
    return {
        "status": "completed",
        "replay_run_id": replay_run_id,
        "snapshot_id": str(snapshot_id).strip(),
        "selected_action": {
            "type": str(selected_action.get("type", "")).strip(),
            "target": str(selected_action.get("target", "")).strip(),
        },
        "comparison": comparison,
        "replay_result": _extract_replay_payload(replay_result),
    }
