from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.config import settings
from app.core.logger import save_what_if_comparison, save_what_if_replay
from app.core.what_if_replay import replay_case_from_snapshot
from app.data.loader import load_processed_cases, load_raw_cases
from app.data.transform import transform_case


def _load_cases() -> list[dict[str, Any]]:
    if settings.USE_PROCESSED_CASES and settings.PROCESSED_DATA_PATH.exists():
        return load_processed_cases(settings.PROCESSED_DATA_PATH)
    raw_cases = load_raw_cases(settings.RAW_DATA_PATH)
    return [transform_case(case, idx) for idx, case in enumerate(raw_cases)]


def _get_case_map() -> dict[str, dict[str, Any]]:
    return {
        str(case.get("case_id", "")).strip(): case
        for case in _load_cases()
        if str(case.get("case_id", "")).strip()
    }


def _get_latest_run_id() -> str:
    run_dirs = sorted([path.name for path in settings.RESULTS_DIR.iterdir() if path.is_dir()])
    if not run_dirs:
        raise FileNotFoundError("No run directories found under outputs/results.")
    return run_dirs[-1]


def _iter_results(run_id: str) -> list[dict[str, Any]]:
    run_dir = settings.RESULTS_DIR / run_id
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")
    results: list[dict[str, Any]] = []
    for result_path in sorted(run_dir.glob("case_*_result.json")):
        results.append(json.loads(result_path.read_text(encoding="utf-8")))
    return results


def _specialty_snapshots(result: dict[str, Any], snapshot_scope: str) -> list[dict[str, Any]]:
    allowed_nodes = {"specialty_next_step", "specialty_finalize"}
    if snapshot_scope == "next_step":
        allowed_nodes = {"specialty_next_step"}
    elif snapshot_scope == "finalize":
        allowed_nodes = {"specialty_finalize"}

    snapshots = [
        snapshot
        for snapshot in (result.get("decision_snapshots", []) or [])
        if str(snapshot.get("node", "")).strip() in allowed_nodes
    ]
    node_priority = {"specialty_next_step": 0, "specialty_finalize": 1}
    return sorted(
        snapshots,
        key=lambda item: (
            int(item.get("turn_index", 0) or 0),
            node_priority.get(str(item.get("node", "")).strip(), 9),
        ),
    )


def _candidate_targets(snapshot: dict[str, Any], action_type: str) -> list[str]:
    values: list[str] = []
    for option in snapshot.get("alternatives", []) or []:
        if str(option.get("type", "")).strip() != action_type:
            continue
        target = str(option.get("target", "")).strip()
        if target not in values:
            values.append(target)
    return values


def _choose_selected_action(
    *,
    snapshot: dict[str, Any],
    mode: str,
) -> dict[str, str] | None:
    proposed_action = dict(snapshot.get("proposed_action", {}) or {})
    proposed_type = str(proposed_action.get("type", "")).strip()
    proposed_target = str(proposed_action.get("target", "")).strip()
    alternatives = list(snapshot.get("alternatives", []) or [])

    if mode == "best_alternative":
        for option in alternatives:
            option_type = str(option.get("type", "")).strip()
            option_target = str(option.get("target", "")).strip()
            if option_type != proposed_type or option_target != proposed_target:
                return {"type": option_type, "target": option_target}
        return None

    if mode == "refine_again":
        targets = _candidate_targets(snapshot, "refine_again")
        if targets or any(str(option.get("type", "")).strip() == "refine_again" for option in alternatives):
            return {"type": "refine_again", "target": ""}
        return None

    if mode == "request_test":
        targets = _candidate_targets(snapshot, "request_test")
        if not targets:
            return None
        return {"type": "request_test", "target": targets[0]}

    if mode == "diagnose_now":
        if any(str(option.get("type", "")).strip() == "diagnose_now" for option in alternatives):
            return {"type": "diagnose_now", "target": ""}
        return None

    raise ValueError(f"Unsupported mode: {mode}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run batch what-if replay for specialty same-department finalize snapshots."
    )
    parser.add_argument("--run-id", default="", help="Source run id under outputs/results. Defaults to latest run.")
    parser.add_argument(
        "--mode",
        choices=["best_alternative", "refine_again", "request_test", "diagnose_now"],
        default="best_alternative",
        help="Which specialty alternative to replay.",
    )
    parser.add_argument(
        "--snapshot-scope",
        choices=["all", "next_step", "finalize"],
        default="all",
        help="Which specialty snapshot types to consider. 'all' prefers the earliest actionable specialty snapshot.",
    )
    parser.add_argument(
        "--include-department-incorrect",
        action="store_true",
        help="Include cases where department was also incorrect. Default focuses on same-department misses.",
    )
    parser.add_argument(
        "--include-diagnosis-correct",
        action="store_true",
        help="Include cases whose diagnosis was already correct.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Optional max number of cases to replay.")
    parser.add_argument(
        "--replay-prefix",
        default="specialty_batch",
        help="Prefix for replay run ids and summary naming.",
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
    results = _iter_results(run_id)
    case_map = _get_case_map()

    mode = str(args.mode).strip()
    include_department_incorrect = bool(args.include_department_incorrect)
    include_diagnosis_correct = bool(args.include_diagnosis_correct)
    limit = int(args.limit or 0)
    replay_prefix = str(args.replay_prefix).strip() or "specialty_batch"
    max_turns = int(args.max_turns)
    snapshot_scope = str(args.snapshot_scope).strip()

    summary_rows: list[dict[str, Any]] = []
    replay_count = 0

    for result in results:
        diagnosis_correct = bool(result.get("diagnosis_correct"))
        department_correct = bool(result.get("department_correct"))
        if not include_diagnosis_correct and diagnosis_correct:
            continue
        if not include_department_incorrect and not department_correct:
            continue

        snapshots = _specialty_snapshots(result, snapshot_scope)
        if not snapshots:
            continue

        selected_snapshot = None
        selected_action = None
        for snapshot in snapshots:
            candidate_action = _choose_selected_action(snapshot=snapshot, mode=mode)
            if candidate_action:
                selected_snapshot = snapshot
                selected_action = candidate_action
                break
        if not selected_snapshot or not selected_action:
            continue

        case_id = str(result.get("case_id", "")).strip()
        case = case_map.get(case_id)
        if not case:
            continue

        replay_count += 1
        replay_run_id = f"{replay_prefix}_{replay_count:02d}"
        replay_result = replay_case_from_snapshot(
            case=case,
            original_result=result,
            snapshot=selected_snapshot,
            selected_action=selected_action,
            run_id=replay_run_id,
            max_turns=max_turns,
        )
        comparison = dict(replay_result.get("what_if_replay", {}).get("comparison", {}) or {})
        save_what_if_replay(case_id, replay_result, replay_run_id)
        save_what_if_comparison(case_id, comparison, replay_run_id)
        summary_rows.append(
            {
                "replay_run_id": replay_run_id,
                "case_id": case_id,
                "snapshot_id": str(selected_snapshot.get("snapshot_id", "")).strip(),
                "snapshot_node": str(selected_snapshot.get("node", "")).strip(),
                "selected_action": selected_action,
                "original_diagnosis": str(result.get("predicted_diagnosis", "")).strip(),
                "original_department": str(result.get("predicted_department", "")).strip(),
                "replay_diagnosis": str(replay_result.get("predicted_diagnosis", "")).strip(),
                "replay_department": str(replay_result.get("predicted_department", "")).strip(),
                "comparison": comparison,
            }
        )
        print(
            f"{replay_run_id} | {case_id} | mode={mode} | "
            f"improved={comparison.get('improved', False)} | reward_delta={comparison.get('reward_delta', 0.0)}"
        )

        if limit > 0 and replay_count >= limit:
            break

    summary = {
        "source_run_id": run_id,
        "mode": mode,
        "snapshot_scope": snapshot_scope,
        "same_department_focus": not include_department_incorrect,
        "diagnosis_incorrect_focus": not include_diagnosis_correct,
        "replay_count": replay_count,
        "improved_count": sum(1 for row in summary_rows if bool((row.get("comparison", {}) or {}).get("improved", False))),
        "rows": summary_rows,
    }

    summary_dir = settings.WHAT_IF_DIR / "batch_summaries"
    summary_dir.mkdir(parents=True, exist_ok=True)
    summary_path = summary_dir / f"{replay_prefix}_{mode}_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"summary_path={summary_path}")


if __name__ == "__main__":
    main()
