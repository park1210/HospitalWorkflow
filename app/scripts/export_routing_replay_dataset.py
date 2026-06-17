from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.config import settings


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _get_latest_direct_summary() -> Path:
    summary_dir = settings.WHAT_IF_DIR / "batch_summaries"
    candidates = sorted(summary_dir.glob("*_direct_reroute_summary.json"))
    if not candidates:
        raise FileNotFoundError(f"No direct reroute batch summaries found in {summary_dir}")
    return candidates[-1]


def _get_snapshot(result: dict[str, Any], snapshot_id: str) -> dict[str, Any]:
    for snapshot in result.get("decision_snapshots", []) or []:
        if str(snapshot.get("snapshot_id", "")).strip() == snapshot_id:
            return snapshot
    raise KeyError(f"Snapshot not found in result: {snapshot_id}")


def _improvement_type(comparison: dict[str, Any]) -> str:
    original = comparison.get("original", {}) or {}
    replay = comparison.get("replay", {}) or {}

    diagnosis_changed = bool(replay.get("diagnosis_correct", False)) and not bool(original.get("diagnosis_correct", False))
    department_changed = bool(replay.get("department_correct", False)) and not bool(original.get("department_correct", False))

    if diagnosis_changed and department_changed:
        return "diagnosis_and_department_recovered"
    if diagnosis_changed:
        return "diagnosis_only_recovered"
    if department_changed:
        return "department_only_recovered"
    if bool(comparison.get("improved", False)):
        return "reward_only_improved"
    return "no_recovery"


def _state_excerpt(snapshot: dict[str, Any]) -> dict[str, Any]:
    state = snapshot.get("state_snapshot", {}) or {}
    objective_findings = state.get("objective_findings", []) or []
    known_information = state.get("known_information", []) or []

    return {
        "er_working_diagnosis": str(state.get("er_working_diagnosis", "")).strip(),
        "responsible_department": str(state.get("responsible_department", "")).strip(),
        "department_routing_candidates": list(state.get("department_routing_candidates", []) or []),
        "department_routing_scores": dict(state.get("department_routing_scores", {}) or {}),
        "recommended_tests": list(state.get("recommended_tests", []) or []),
        "requested_tests": list(state.get("requested_tests", []) or []),
        "objective_findings_count": len(objective_findings),
        "known_information_count": len(known_information),
    }


def _record_from_row(
    *,
    row: dict[str, Any],
    result: dict[str, Any],
    source_run_id: str,
    mode: str,
) -> dict[str, Any]:
    snapshot_id = str(row.get("snapshot_id", "")).strip()
    snapshot = _get_snapshot(result, snapshot_id)
    comparison = dict(row.get("comparison", {}) or {})

    return {
        "source_run_id": source_run_id,
        "mode": mode,
        "case_id": str(row.get("case_id", "")).strip(),
        "snapshot_id": snapshot_id,
        "node": str(snapshot.get("node", "")).strip(),
        "turn_index": int(snapshot.get("turn_index", 0) or 0),
        "proposed_action": dict(snapshot.get("proposed_action", {}) or {}),
        "selected_action": dict(row.get("selected_action", {}) or {}),
        "alternatives": list(snapshot.get("alternatives", []) or []),
        "snapshot_metadata": dict(snapshot.get("metadata", {}) or {}),
        "state_excerpt": _state_excerpt(snapshot),
        "ground_truth_diagnosis": str(result.get("ground_truth", "")).strip(),
        "ground_truth_department": str(result.get("ground_truth_department", "")).strip(),
        "original_result": dict(comparison.get("original", {}) or {}),
        "replay_result": dict(comparison.get("replay", {}) or {}),
        "reward_delta": float(comparison.get("reward_delta", 0.0) or 0.0),
        "improved": bool(comparison.get("improved", False)),
        "improvement_type": _improvement_type(comparison),
        "final_decision_source": str(result.get("final_decision_source", "")).strip(),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export routing replay batch results into a compact dataset for analysis or policy updates."
    )
    parser.add_argument(
        "--summary-path",
        default="",
        help="Path to a routing replay batch summary. Defaults to latest direct reroute summary.",
    )
    parser.add_argument(
        "--improved-only",
        action="store_true",
        help="Export only improved rows.",
    )
    parser.add_argument(
        "--output-prefix",
        default="routing_replay_dataset",
        help="Output prefix under outputs/what_if/datasets.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    summary_path = Path(str(args.summary_path).strip()) if str(args.summary_path).strip() else _get_latest_direct_summary()
    summary = _load_json(summary_path)

    source_run_id = str(summary.get("source_run_id", "")).strip()
    mode = str(summary.get("mode", "")).strip()
    results_dir = settings.RESULTS_DIR / source_run_id
    if not results_dir.exists():
        raise FileNotFoundError(f"Results directory not found for source run: {results_dir}")

    records: list[dict[str, Any]] = []
    for row in summary.get("rows", []) or []:
        comparison = dict(row.get("comparison", {}) or {})
        if args.improved_only and not bool(comparison.get("improved", False)):
            continue

        case_id = str(row.get("case_id", "")).strip()
        result_path = results_dir / f"{case_id}_result.json"
        result = _load_json(result_path)
        records.append(
            _record_from_row(
                row=row,
                result=result,
                source_run_id=source_run_id,
                mode=mode,
            )
        )

    output_dir = settings.WHAT_IF_DIR / "datasets"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_prefix = str(args.output_prefix).strip() or "routing_replay_dataset"
    if args.improved_only:
        output_prefix = f"{output_prefix}_improved_only"

    jsonl_path = output_dir / f"{output_prefix}.jsonl"
    summary_out_path = output_dir / f"{output_prefix}_summary.json"

    with jsonl_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    dataset_summary = {
        "source_summary_path": str(summary_path),
        "source_run_id": source_run_id,
        "mode": mode,
        "record_count": len(records),
        "improved_count": sum(1 for record in records if bool(record.get("improved", False))),
        "improvement_type_counts": {
            label: sum(1 for record in records if str(record.get("improvement_type", "")) == label)
            for label in [
                "diagnosis_and_department_recovered",
                "diagnosis_only_recovered",
                "department_only_recovered",
                "reward_only_improved",
                "no_recovery",
            ]
        },
        "average_reward_delta": round(
            sum(float(record.get("reward_delta", 0.0) or 0.0) for record in records) / len(records),
            4,
        )
        if records
        else 0.0,
        "jsonl_path": str(jsonl_path),
    }
    summary_out_path.write_text(json.dumps(dataset_summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"record_count={dataset_summary['record_count']}")
    print(f"improved_count={dataset_summary['improved_count']}")
    print(f"jsonl_path={jsonl_path}")
    print(f"summary_path={summary_out_path}")


if __name__ == "__main__":
    main()
