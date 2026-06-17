from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.config import settings


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Dataset file not found: {path}")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _get_latest_dataset() -> Path:
    dataset_dir = settings.WHAT_IF_DIR / "datasets"
    candidates = sorted(path for path in dataset_dir.glob("*.jsonl") if path.is_file())
    if not candidates:
        raise FileNotFoundError(f"No routing replay datasets found in {dataset_dir}")
    return candidates[-1]


def _safe_div(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _transition_key(record: dict[str, Any]) -> str:
    original = str((record.get("original_result", {}) or {}).get("department", "")).strip()
    selected = str((record.get("selected_action", {}) or {}).get("target", "")).strip()
    return f"{original} -> {selected}"


def _overview(records: list[dict[str, Any]]) -> dict[str, Any]:
    reward_deltas = [float(record.get("reward_delta", 0.0) or 0.0) for record in records]
    improved_records = [record for record in records if bool(record.get("improved", False))]
    full_recovery_records = [
        record for record in records
        if str(record.get("improvement_type", "")) == "diagnosis_and_department_recovered"
    ]
    dept_recovery_records = [
        record for record in records
        if str(record.get("improvement_type", "")) == "department_only_recovered"
    ]

    return {
        "record_count": len(records),
        "improved_count": len(improved_records),
        "improved_rate": _safe_div(len(improved_records), len(records)),
        "full_recovery_count": len(full_recovery_records),
        "full_recovery_rate": _safe_div(len(full_recovery_records), len(records)),
        "department_only_recovery_count": len(dept_recovery_records),
        "department_only_recovery_rate": _safe_div(len(dept_recovery_records), len(records)),
        "average_reward_delta": _mean(reward_deltas),
        "average_reward_delta_improved_only": _mean(
            [float(record.get("reward_delta", 0.0) or 0.0) for record in improved_records]
        ),
    }


def _improvement_type_breakdown(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = defaultdict(int)
    for record in records:
        counts[str(record.get("improvement_type", "")).strip() or "unknown"] += 1
    rows = []
    for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        rows.append(
            {
                "improvement_type": label,
                "count": count,
                "rate": _safe_div(count, len(records)),
            }
        )
    return rows


def _department_transition_summary(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[_transition_key(record)].append(record)

    rows: list[dict[str, Any]] = []
    for transition, items in sorted(grouped.items()):
        improved = [item for item in items if bool(item.get("improved", False))]
        full_recovery = [
            item for item in items
            if str(item.get("improvement_type", "")) == "diagnosis_and_department_recovered"
        ]
        dept_only = [
            item for item in items
            if str(item.get("improvement_type", "")) == "department_only_recovered"
        ]
        rows.append(
            {
                "transition": transition,
                "count": len(items),
                "improved_count": len(improved),
                "improved_rate": _safe_div(len(improved), len(items)),
                "full_recovery_count": len(full_recovery),
                "department_only_recovery_count": len(dept_only),
                "average_reward_delta": _mean([float(item.get("reward_delta", 0.0) or 0.0) for item in items]),
            }
        )

    rows.sort(key=lambda row: (-row["improved_rate"], -row["average_reward_delta"], row["transition"]))
    return rows


def _score_gap_buckets(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        scores = dict((record.get("snapshot_metadata", {}) or {}).get("routing_scores", {}) or {})
        original_department = str((record.get("original_result", {}) or {}).get("department", "")).strip()
        selected_department = str((record.get("selected_action", {}) or {}).get("target", "")).strip()
        original_score = float(scores.get(original_department, 0.0) or 0.0)
        selected_score = float(scores.get(selected_department, 0.0) or 0.0)
        gap = round(abs(selected_score - original_score), 4)
        if gap < 1.0:
            label = "<1.0"
        elif gap < 3.0:
            label = "1.0-2.99"
        else:
            label = ">=3.0"
        enriched = dict(record)
        enriched["_score_gap"] = gap
        buckets[label].append(enriched)

    labels = ["<1.0", "1.0-2.99", ">=3.0"]
    rows: list[dict[str, Any]] = []
    for label in labels:
        items = buckets.get(label, [])
        rows.append(
            {
                "score_gap_bucket": label,
                "count": len(items),
                "improved_count": sum(1 for item in items if bool(item.get("improved", False))),
                "improved_rate": _safe_div(sum(1 for item in items if bool(item.get("improved", False))), len(items)),
                "average_reward_delta": _mean([float(item.get("reward_delta", 0.0) or 0.0) for item in items]),
                "average_score_gap": _mean([float(item.get("_score_gap", 0.0) or 0.0) for item in items]),
            }
        )
    return rows


def _top_cases(records: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    rows = sorted(
        records,
        key=lambda record: (
            -float(record.get("reward_delta", 0.0) or 0.0),
            str(record.get("case_id", "")),
        ),
    )
    top_rows: list[dict[str, Any]] = []
    for record in rows[:limit]:
        top_rows.append(
            {
                "case_id": str(record.get("case_id", "")).strip(),
                "transition": _transition_key(record),
                "improvement_type": str(record.get("improvement_type", "")).strip(),
                "reward_delta": float(record.get("reward_delta", 0.0) or 0.0),
                "original_diagnosis": str((record.get("original_result", {}) or {}).get("diagnosis", "")).strip(),
                "replay_diagnosis": str((record.get("replay_result", {}) or {}).get("diagnosis", "")).strip(),
                "original_department": str((record.get("original_result", {}) or {}).get("department", "")).strip(),
                "replay_department": str((record.get("replay_result", {}) or {}).get("department", "")).strip(),
            }
        )
    return top_rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze exported routing replay dataset and summarize recovery patterns."
    )
    parser.add_argument(
        "--dataset-path",
        default="",
        help="Path to routing replay dataset jsonl. Defaults to latest dataset.",
    )
    parser.add_argument(
        "--output-name",
        default="routing_replay_dataset_analysis.json",
        help="Output filename under outputs/what_if/datasets.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    dataset_path = Path(str(args.dataset_path).strip()) if str(args.dataset_path).strip() else _get_latest_dataset()
    records = _load_jsonl(dataset_path)

    analysis = {
        "dataset_path": str(dataset_path),
        "overview": _overview(records),
        "improvement_type_breakdown": _improvement_type_breakdown(records),
        "department_transition_summary": _department_transition_summary(records),
        "score_gap_buckets": _score_gap_buckets(records),
        "top_cases_by_reward_delta": _top_cases(records, limit=10),
    }

    output_dir = settings.WHAT_IF_DIR / "datasets"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_name = str(args.output_name).strip() or "routing_replay_dataset_analysis.json"
    output_path = output_dir / output_name
    output_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")

    overview = analysis["overview"]
    print(f"record_count={overview['record_count']}")
    print(f"improved_count={overview['improved_count']}")
    print(f"full_recovery_count={overview['full_recovery_count']}")
    print(f"average_reward_delta={overview['average_reward_delta']}")
    print(f"output_path={output_path}")


if __name__ == "__main__":
    main()
