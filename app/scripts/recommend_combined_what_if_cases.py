from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.config import settings
from app.utils.what_if_recommendation_policy import get_combined_bucket_rank, get_combined_type_rank


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Recommendation file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_recommendation(kind: str) -> Path:
    rec_dir = settings.WHAT_IF_DIR / "recommendations"
    if kind == "routing":
        pattern = "routing_replay_recommendations_*.json"
    elif kind == "specialty":
        pattern = "specialty_replay_recommendations_*.json"
    else:
        raise ValueError(f"Unsupported kind: {kind}")
    candidates = sorted(path for path in rec_dir.glob(pattern) if path.is_file())
    if not candidates:
        raise FileNotFoundError(f"No {kind} recommendation files found in {rec_dir}")
    return candidates[-1]


def _bucket_rank(priority_bucket: str, review_subbucket: str) -> int:
    return get_combined_bucket_rank(priority_bucket, review_subbucket)


def _type_rank(recommendation_type: str, row: dict[str, Any]) -> int:
    return get_combined_type_rank(recommendation_type, bool(row.get("department_correct", False)))


def _normalize_row(kind: str, row: dict[str, Any]) -> dict[str, Any]:
    recommendation = dict(row.get("recommendation", {}) or {})
    action = dict(recommendation.get("selected_action", {}) or {})
    priority_bucket = str(row.get("priority_bucket", "")).strip() or "low_priority"
    review_subbucket = str(row.get("review_subbucket", "")).strip()
    score = float(recommendation.get("score", 0.0) or 0.0)
    return {
        "type": kind,
        "case_id": str(row.get("case_id", "")).strip(),
        "predicted_diagnosis": str(row.get("predicted_diagnosis", "")).strip(),
        "predicted_department": str(row.get("predicted_department", "")).strip(),
        "ground_truth": str(row.get("ground_truth", "")).strip(),
        "ground_truth_department": str(row.get("ground_truth_department", "")).strip(),
        "department_correct": bool(row.get("department_correct", False)),
        "diagnosis_correct": bool(row.get("diagnosis_correct", False)),
        "priority_bucket": priority_bucket,
        "review_subbucket": review_subbucket,
        "bucket_rank": _bucket_rank(priority_bucket, review_subbucket),
        "type_rank": _type_rank(kind, row),
        "score": score,
        "snapshot_id": str(recommendation.get("snapshot_id", "")).strip(),
        "snapshot_node": str(recommendation.get("snapshot_node", "")).strip(),
        "selected_action": action,
        "reasons": list(recommendation.get("reasons", []) or []),
        "recommendation": recommendation,
    }


def _collect_rows(payload: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in payload.get("rows", []) or []:
        normalized = _normalize_row(kind, row)
        if normalized["case_id"]:
            rows.append(normalized)
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Combine routing and specialty what-if recommendations into a single ranked view."
    )
    parser.add_argument(
        "--routing-path",
        default="",
        help="Optional explicit routing recommendation file. Defaults to latest routing file.",
    )
    parser.add_argument(
        "--specialty-path",
        default="",
        help="Optional explicit specialty recommendation file. Defaults to latest specialty file.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of top case recommendations to keep.",
    )
    parser.add_argument(
        "--output-name",
        default="",
        help="Optional output filename under outputs/what_if/recommendations.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    routing_path = Path(str(args.routing_path).strip()) if str(args.routing_path).strip() else _latest_recommendation("routing")
    specialty_path = (
        Path(str(args.specialty_path).strip()) if str(args.specialty_path).strip() else _latest_recommendation("specialty")
    )

    routing_payload = _load_json(routing_path)
    specialty_payload = _load_json(specialty_path)

    routing_run_id = str(routing_payload.get("source_run_id", "")).strip()
    specialty_run_id = str(specialty_payload.get("source_run_id", "")).strip()
    source_run_id = routing_run_id or specialty_run_id
    if routing_run_id and specialty_run_id and routing_run_id != specialty_run_id:
        raise ValueError(
            f"Routing and specialty recommendation files come from different runs: "
            f"{routing_run_id} vs {specialty_run_id}"
        )

    combined_rows = _collect_rows(routing_payload, "routing") + _collect_rows(specialty_payload, "specialty")

    by_case: dict[str, list[dict[str, Any]]] = {}
    for row in combined_rows:
        by_case.setdefault(str(row.get("case_id", "")).strip(), []).append(row)

    top_rows: list[dict[str, Any]] = []
    for case_id, candidates in by_case.items():
        ordered = sorted(
            candidates,
            key=lambda item: (
                int(item.get("bucket_rank", 9)),
                int(item.get("type_rank", 9)),
                -float(item.get("score", 0.0) or 0.0),
                str(item.get("snapshot_node", "")),
            ),
        )
        top = dict(ordered[0])
        top["alternative_count"] = len(ordered)
        top["all_candidates"] = [
            {
                "type": candidate.get("type", ""),
                "priority_bucket": candidate.get("priority_bucket", ""),
                "review_subbucket": candidate.get("review_subbucket", ""),
                "score": candidate.get("score", 0.0),
                "snapshot_node": candidate.get("snapshot_node", ""),
                "selected_action": candidate.get("selected_action", {}),
            }
            for candidate in ordered
        ]
        top_rows.append(top)

    top_rows.sort(
        key=lambda item: (
            int(item.get("bucket_rank", 9)),
            int(item.get("type_rank", 9)),
            -float(item.get("score", 0.0) or 0.0),
            str(item.get("case_id", "")),
        )
    )
    limit = max(int(args.limit or 0), 0)
    if limit:
        top_rows = top_rows[:limit]

    summary = {
        "source_run_id": source_run_id,
        "routing_recommendation_path": str(routing_path),
        "specialty_recommendation_path": str(specialty_path),
        "combined_row_count": len(combined_rows),
        "case_recommendation_count": len(top_rows),
        "bucket_summary": {
            "priority_replay": sum(1 for row in top_rows if row.get("priority_bucket") == "priority_replay"),
            "review_high": sum(1 for row in top_rows if row.get("review_subbucket") == "review_high"),
            "review_low": sum(1 for row in top_rows if row.get("review_subbucket") == "review_low"),
        },
        "rows": top_rows,
    }

    output_dir = settings.WHAT_IF_DIR / "recommendations"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_name = str(args.output_name).strip() or f"combined_what_if_recommendations_{source_run_id}.json"
    output_path = output_dir / output_name
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"source_run_id={source_run_id}")
    print(f"combined_row_count={len(combined_rows)}")
    print(f"case_recommendation_count={len(top_rows)}")
    for row in top_rows[: min(8, len(top_rows))]:
        action = dict(row.get("selected_action", {}) or {})
        print(
            f"{row['case_id']} | {row.get('type')} | {row.get('priority_bucket')}/{row.get('review_subbucket', '')} | "
            f"score={row.get('score')} | action={action.get('type')}:{action.get('target', '')}"
        )
    print(f"output_path={output_path}")


if __name__ == "__main__":
    main()
