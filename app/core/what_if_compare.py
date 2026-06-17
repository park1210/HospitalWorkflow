from __future__ import annotations

from typing import Any


def compare_original_and_replay(
    original_result: dict[str, Any],
    replay_result: dict[str, Any],
    snapshot: dict[str, Any],
    selected_action: dict[str, str],
) -> dict[str, Any]:
    original_summary = {
        "diagnosis": str(original_result.get("predicted_diagnosis", "")).strip(),
        "department": str(original_result.get("predicted_department", "")).strip(),
        "diagnosis_correct": bool(original_result.get("diagnosis_correct", False)),
        "department_correct": bool(original_result.get("department_correct", False)),
        "episode_reward": float(original_result.get("episode_reward", 0.0) or 0.0),
    }
    replay_summary = {
        "diagnosis": str(replay_result.get("predicted_diagnosis", "")).strip(),
        "department": str(replay_result.get("predicted_department", "")).strip(),
        "diagnosis_correct": bool(replay_result.get("diagnosis_correct", False)),
        "department_correct": bool(replay_result.get("department_correct", False)),
        "episode_reward": float(replay_result.get("episode_reward", 0.0) or 0.0),
    }
    reward_delta = replay_summary["episode_reward"] - original_summary["episode_reward"]
    improved = (
        (not original_summary["diagnosis_correct"] and replay_summary["diagnosis_correct"])
        or (not original_summary["department_correct"] and replay_summary["department_correct"])
        or reward_delta > 0.0
    )
    return {
        "snapshot_id": str(snapshot.get("snapshot_id", "")).strip(),
        "case_id": str(snapshot.get("case_id", "")).strip(),
        "node": str(snapshot.get("node", "")).strip(),
        "turn_index": int(snapshot.get("turn_index", 0) or 0),
        "selected_action": {
            "type": str(selected_action.get("type", "")).strip(),
            "target": str(selected_action.get("target", "")).strip(),
        },
        "original": original_summary,
        "replay": replay_summary,
        "reward_delta": round(reward_delta, 4),
        "improved": bool(improved),
    }
