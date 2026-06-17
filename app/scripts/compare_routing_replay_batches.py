from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.config import settings


def _load_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Summary file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _get_latest_summary(mode: str) -> Path:
    summary_dir = settings.WHAT_IF_DIR / "batch_summaries"
    candidates = sorted(summary_dir.glob(f"*_{mode}_summary.json"))
    if not candidates:
        raise FileNotFoundError(f"No batch summary found for mode '{mode}' in {summary_dir}")
    return candidates[-1]


def _row_map(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = summary.get("rows", []) or []
    return {
        str(row.get("case_id", "")).strip(): row
        for row in rows
        if str(row.get("case_id", "")).strip()
    }


def _count_true(rows: list[dict[str, Any]], key: str) -> int:
    return sum(1 for row in rows if bool((row.get("comparison", {}) or {}).get(key, False)))


def _sum_reward_delta(rows: list[dict[str, Any]]) -> float:
    return round(
        sum(float((row.get("comparison", {}) or {}).get("reward_delta", 0.0) or 0.0) for row in rows),
        4,
    )


def _mode_summary(summary: dict[str, Any]) -> dict[str, Any]:
    rows = summary.get("rows", []) or []
    replay_count = int(summary.get("replay_count", len(rows)) or 0)
    improved_count = _count_true(rows, "improved")
    diagnosis_correct_count = _count_true(
        [{"comparison": {"improved": bool((row.get("comparison", {}) or {}).get("replay", {}).get("diagnosis_correct", False))}} for row in rows],
        "improved",
    )
    department_correct_count = _count_true(
        [{"comparison": {"improved": bool((row.get("comparison", {}) or {}).get("replay", {}).get("department_correct", False))}} for row in rows],
        "improved",
    )
    return {
        "source_run_id": str(summary.get("source_run_id", "")).strip(),
        "mode": str(summary.get("mode", "")).strip(),
        "replay_count": replay_count,
        "improved_count": improved_count,
        "improved_rate": round((improved_count / replay_count), 4) if replay_count else 0.0,
        "replay_diagnosis_correct_count": diagnosis_correct_count,
        "replay_department_correct_count": department_correct_count,
        "total_reward_delta": _sum_reward_delta(rows),
        "average_reward_delta": round(_sum_reward_delta(rows) / replay_count, 4) if replay_count else 0.0,
    }


def _matched_case_rows(
    direct_summary: dict[str, Any],
    consult_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    direct_map = _row_map(direct_summary)
    consult_map = _row_map(consult_summary)
    matched_case_ids = sorted(set(direct_map) & set(consult_map))

    rows: list[dict[str, Any]] = []
    for case_id in matched_case_ids:
        direct_row = direct_map[case_id]
        consult_row = consult_map[case_id]
        direct_comp = dict(direct_row.get("comparison", {}) or {})
        consult_comp = dict(consult_row.get("comparison", {}) or {})
        direct_delta = float(direct_comp.get("reward_delta", 0.0) or 0.0)
        consult_delta = float(consult_comp.get("reward_delta", 0.0) or 0.0)

        rows.append(
            {
                "case_id": case_id,
                "original": {
                    "diagnosis": str(direct_row.get("original_diagnosis", "")).strip(),
                    "department": str(direct_row.get("original_department", "")).strip(),
                },
                "direct_reroute": {
                    "snapshot_id": str(direct_row.get("snapshot_id", "")).strip(),
                    "selected_action": direct_row.get("selected_action", {}),
                    "replay_diagnosis": str(direct_row.get("replay_diagnosis", "")).strip(),
                    "replay_department": str(direct_row.get("replay_department", "")).strip(),
                    "improved": bool(direct_comp.get("improved", False)),
                    "reward_delta": direct_delta,
                    "diagnosis_correct": bool((direct_comp.get("replay", {}) or {}).get("diagnosis_correct", False)),
                    "department_correct": bool((direct_comp.get("replay", {}) or {}).get("department_correct", False)),
                },
                "consult_first": {
                    "snapshot_id": str(consult_row.get("snapshot_id", "")).strip(),
                    "selected_action": consult_row.get("selected_action", {}),
                    "replay_diagnosis": str(consult_row.get("replay_diagnosis", "")).strip(),
                    "replay_department": str(consult_row.get("replay_department", "")).strip(),
                    "improved": bool(consult_comp.get("improved", False)),
                    "reward_delta": consult_delta,
                    "diagnosis_correct": bool((consult_comp.get("replay", {}) or {}).get("diagnosis_correct", False)),
                    "department_correct": bool((consult_comp.get("replay", {}) or {}).get("department_correct", False)),
                },
                "winner": (
                    "direct_reroute"
                    if direct_delta > consult_delta
                    else "consult_first"
                    if consult_delta > direct_delta
                    else "tie"
                ),
                "reward_delta_gap": round(direct_delta - consult_delta, 4),
            }
        )
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare routing replay batch summaries for direct reroute and consult-first modes."
    )
    parser.add_argument(
        "--direct-summary",
        default="",
        help="Path to direct_reroute batch summary. Defaults to latest matching summary.",
    )
    parser.add_argument(
        "--consult-summary",
        default="",
        help="Path to consult_first batch summary. Defaults to latest matching summary.",
    )
    parser.add_argument(
        "--output-name",
        default="routing_mode_comparison.json",
        help="Output filename under outputs/what_if/batch_summaries.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    direct_path = Path(str(args.direct_summary).strip()) if str(args.direct_summary).strip() else _get_latest_summary("direct_reroute")
    consult_path = Path(str(args.consult_summary).strip()) if str(args.consult_summary).strip() else _get_latest_summary("consult_first")

    direct_summary = _load_summary(direct_path)
    consult_summary = _load_summary(consult_path)

    matched_rows = _matched_case_rows(direct_summary, consult_summary)
    direct_mode = _mode_summary(direct_summary)
    consult_mode = _mode_summary(consult_summary)

    comparison = {
        "direct_summary_path": str(direct_path),
        "consult_summary_path": str(consult_path),
        "direct_reroute": direct_mode,
        "consult_first": consult_mode,
        "matched_case_count": len(matched_rows),
        "direct_wins": sum(1 for row in matched_rows if row.get("winner") == "direct_reroute"),
        "consult_wins": sum(1 for row in matched_rows if row.get("winner") == "consult_first"),
        "ties": sum(1 for row in matched_rows if row.get("winner") == "tie"),
        "matched_cases": matched_rows,
    }

    summary_dir = settings.WHAT_IF_DIR / "batch_summaries"
    summary_dir.mkdir(parents=True, exist_ok=True)
    output_name = str(args.output_name).strip() or "routing_mode_comparison.json"
    output_path = summary_dir / output_name
    output_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"direct_replay_count={direct_mode['replay_count']}")
    print(f"direct_improved_count={direct_mode['improved_count']}")
    print(f"consult_replay_count={consult_mode['replay_count']}")
    print(f"consult_improved_count={consult_mode['improved_count']}")
    print(f"matched_case_count={comparison['matched_case_count']}")
    print(f"direct_wins={comparison['direct_wins']}")
    print(f"consult_wins={comparison['consult_wins']}")
    print(f"ties={comparison['ties']}")
    print(f"output_path={output_path}")


if __name__ == "__main__":
    main()
