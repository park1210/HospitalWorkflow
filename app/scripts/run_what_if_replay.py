from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.config import settings
from app.core.logger import create_run_id, save_what_if_comparison, save_what_if_replay
from app.core.what_if_replay import get_snapshot_by_id, list_case_snapshots, replay_case_from_snapshot
from app.data.loader import load_processed_cases, load_raw_cases
from app.data.transform import transform_case


def _load_cases() -> list[dict[str, Any]]:
    if settings.USE_PROCESSED_CASES and settings.PROCESSED_DATA_PATH.exists():
        return load_processed_cases(settings.PROCESSED_DATA_PATH)
    raw_cases = load_raw_cases(settings.RAW_DATA_PATH)
    return [transform_case(case, idx) for idx, case in enumerate(raw_cases)]


def _get_latest_run_id() -> str:
    run_dirs = sorted([path.name for path in settings.RESULTS_DIR.iterdir() if path.is_dir()])
    if not run_dirs:
        raise FileNotFoundError("No run directories found under outputs/results.")
    return run_dirs[-1]


def _load_result(run_id: str, case_id: str | None) -> dict[str, Any]:
    run_dir = settings.RESULTS_DIR / run_id
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")

    if case_id:
        result_path = run_dir / f"{case_id}_result.json"
        if not result_path.exists():
            raise FileNotFoundError(f"Result file not found: {result_path}")
    else:
        result_paths = sorted(run_dir.glob("case_*_result.json"))
        if not result_paths:
            raise FileNotFoundError(f"No case result files found in: {run_dir}")
        result_path = result_paths[0]

    return json.loads(result_path.read_text(encoding="utf-8"))


def _get_case_by_case_id(case_id: str) -> dict[str, Any]:
    cases = _load_cases()
    for case in cases:
        if str(case.get("case_id", "")).strip() == case_id:
            return case
    raise KeyError(f"Case not found in dataset: {case_id}")


def _print_snapshots(result: dict[str, Any]) -> None:
    snapshots = list_case_snapshots(result)
    if not snapshots:
        print("No decision snapshots found in this case result.")
        return

    print(f"case_id={result.get('case_id', '')} | snapshots={len(snapshots)}")
    for snapshot in snapshots:
        print(
            f"- {snapshot.get('snapshot_id', '')} | "
            f"node={snapshot.get('node', '')} | "
            f"turn={snapshot.get('turn_index', '')}"
        )
        for option in snapshot.get("alternatives", []):
            print(f"  * {option.get('type', '')} | target={option.get('target', '')}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="List stored what-if decision snapshots or replay a case from a selected snapshot."
    )
    parser.add_argument("--run-id", default="", help="Run id under outputs/results. Defaults to the latest run.")
    parser.add_argument("--case-id", default="", help="Case id to inspect, e.g. case_0000. Defaults to first case in the run.")
    parser.add_argument("--list-snapshots", action="store_true", help="List available snapshots for the selected case.")
    parser.add_argument("--snapshot-id", default="", help="Snapshot id to replay from.")
    parser.add_argument("--action-type", default="", help="Selected replay action type.")
    parser.add_argument("--action-target", default="", help="Selected replay action target.")
    parser.add_argument(
        "--replay-run-id",
        default="",
        help="Optional run id label for replay outputs. Defaults to a generated run id.",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=settings.MAX_TURNS,
        help="Max turns to use during replay. Defaults to current MAX_TURNS setting.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    run_id = str(args.run_id).strip() or _get_latest_run_id()
    case_id = str(args.case_id).strip() or None
    result = _load_result(run_id, case_id)

    if args.list_snapshots:
        _print_snapshots(result)
        return

    snapshot_id = str(args.snapshot_id).strip()
    action_type = str(args.action_type).strip()
    action_target = str(args.action_target).strip()
    if not snapshot_id or not action_type:
        parser.error("--snapshot-id and --action-type are required unless --list-snapshots is used.")

    snapshot = get_snapshot_by_id(result, snapshot_id)
    selected_action = {"type": action_type, "target": action_target}
    case = _get_case_by_case_id(str(result.get("case_id", "")).strip())
    replay_run_id = str(args.replay_run_id).strip() or create_run_id()
    replay_result = replay_case_from_snapshot(
        case=case,
        original_result=result,
        snapshot=snapshot,
        selected_action=selected_action,
        run_id=replay_run_id,
        max_turns=int(args.max_turns),
    )
    comparison = dict(replay_result.get("what_if_replay", {}).get("comparison", {}) or {})
    save_what_if_replay(str(result.get("case_id", "")).strip(), replay_result, replay_run_id)
    save_what_if_comparison(str(result.get("case_id", "")).strip(), comparison, replay_run_id)

    print(f"run_id={run_id}")
    print(f"case_id={result.get('case_id', '')}")
    print(f"snapshot_id={snapshot_id}")
    print(f"selected_action={selected_action}")
    print(
        "original="
        f"{result.get('predicted_diagnosis', '')} / {result.get('predicted_department', '')}"
    )
    print(
        "replay="
        f"{replay_result.get('predicted_diagnosis', '')} / {replay_result.get('predicted_department', '')}"
    )
    print(f"comparison={comparison}")
    print(f"saved_replay_run_id={replay_run_id}")


if __name__ == "__main__":
    main()
