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
from app.utils.department_catalog import normalize_department


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


def _routing_snapshots(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        snapshot
        for snapshot in (result.get("decision_snapshots", []) or [])
        if str(snapshot.get("node", "")).strip() == "er_routing"
    ]


def _candidate_targets(snapshot: dict[str, Any], action_type: str) -> list[str]:
    values: list[str] = []
    for option in snapshot.get("alternatives", []) or []:
        if str(option.get("type", "")).strip() != action_type:
            continue
        target = str(option.get("target", "")).strip()
        if target and target not in values:
            values.append(target)
    return values


def _choose_selected_action(
    *,
    result: dict[str, Any],
    snapshot: dict[str, Any],
    mode: str,
    require_gold_in_alternatives: bool,
) -> dict[str, str] | None:
    gold_department = normalize_department(str(result.get("ground_truth_department", "")).strip(), default="")
    predicted_department = normalize_department(str(result.get("predicted_department", "")).strip(), default="")

    if mode == "direct_reroute":
        action_type = "handoff_department"
    elif mode == "consult_first":
        action_type = "consult_before_handoff"
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    targets = _candidate_targets(snapshot, action_type)
    if not targets:
        return None

    normalized_targets = {normalize_department(target, default=""): target for target in targets}
    if require_gold_in_alternatives:
        selected_target = normalized_targets.get(gold_department, "")
        if not selected_target:
            return None
        return {"type": action_type, "target": selected_target}

    for target in targets:
        if normalize_department(target, default="") != predicted_department:
            return {"type": action_type, "target": target}
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run batch what-if replay for ER routing snapshots."
    )
    parser.add_argument("--run-id", default="", help="Source run id under outputs/results. Defaults to latest run.")
    parser.add_argument(
        "--mode",
        choices=["direct_reroute", "consult_first"],
        default="direct_reroute",
        help="Which ER routing alternative to replay.",
    )
    parser.add_argument(
        "--include-correct-cases",
        action="store_true",
        help="Include cases that were already fully correct. Default is false.",
    )
    parser.add_argument(
        "--allow-non-gold-alternatives",
        action="store_true",
        help="Replay the first non-predicted alternative even if it is not the gold department.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Optional max number of cases to replay.")
    parser.add_argument(
        "--replay-prefix",
        default="routing_batch",
        help="Prefix for replay run ids and summary folder naming.",
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
    include_correct_cases = bool(args.include_correct_cases)
    require_gold_in_alternatives = not bool(args.allow_non_gold_alternatives)
    limit = int(args.limit or 0)
    replay_prefix = str(args.replay_prefix).strip() or "routing_batch"
    max_turns = int(args.max_turns)

    summary_rows: list[dict[str, Any]] = []
    replay_count = 0

    for result in results:
        if not include_correct_cases and bool(result.get("diagnosis_correct")) and bool(result.get("department_correct")):
            continue

        snapshots = _routing_snapshots(result)
        if not snapshots:
            continue

        snapshot = snapshots[-1]
        selected_action = _choose_selected_action(
            result=result,
            snapshot=snapshot,
            mode=mode,
            require_gold_in_alternatives=require_gold_in_alternatives,
        )
        if not selected_action:
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
            snapshot=snapshot,
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
                "snapshot_id": str(snapshot.get("snapshot_id", "")).strip(),
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
        "require_gold_in_alternatives": require_gold_in_alternatives,
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
