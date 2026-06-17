from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.core.what_if_compare import compare_original_and_replay
from app.core.simulator import run_single_case


def list_case_snapshots(result: dict[str, Any]) -> list[dict[str, Any]]:
    snapshots = result.get("decision_snapshots")
    if isinstance(snapshots, list):
        return snapshots
    reasoning_state = result.get("reasoning_state", {}) or {}
    snapshots = reasoning_state.get("decision_snapshots", [])
    return snapshots if isinstance(snapshots, list) else []


def get_snapshot_by_id(result: dict[str, Any], snapshot_id: str) -> dict[str, Any]:
    normalized = str(snapshot_id).strip()
    for snapshot in list_case_snapshots(result):
        if str(snapshot.get("snapshot_id", "")).strip() == normalized:
            return snapshot
    raise KeyError(f"Snapshot not found: {normalized}")


def replay_case_from_snapshot(
    *,
    case: dict[str, Any],
    original_result: dict[str, Any],
    snapshot: dict[str, Any],
    selected_action: dict[str, str],
    run_id: str,
    max_turns: int,
) -> dict[str, Any]:
    override = {
        "snapshot_id": str(snapshot.get("snapshot_id", "")).strip(),
        "case_id": str(snapshot.get("case_id", "")).strip(),
        "node": str(snapshot.get("node", "")).strip(),
        "turn_index": int(snapshot.get("turn_index", 0) or 0),
        "selected_action": {
            "type": str(selected_action.get("type", "")).strip(),
            "target": str(selected_action.get("target", "")).strip(),
        },
        "consumed": False,
    }
    replay_result = run_single_case(
        deepcopy(case),
        run_id,
        max_turns,
        what_if_override=override,
    )
    comparison = compare_original_and_replay(original_result, replay_result, snapshot, selected_action)
    replay_result["what_if_replay"] = {
        "snapshot_id": override["snapshot_id"],
        "selected_action": override["selected_action"],
        "comparison": comparison,
    }
    return replay_result
