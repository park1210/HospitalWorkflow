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


def _case_map() -> dict[str, dict[str, Any]]:
    return {
        str(case.get("case_id", "")).strip(): case
        for case in _load_cases()
        if str(case.get("case_id", "")).strip()
    }


def _get_latest_recommendation() -> Path:
    rec_dir = settings.WHAT_IF_DIR / "recommendations"
    candidates = sorted(path for path in rec_dir.glob("routing_replay_recommendations_*.json") if path.is_file())
    if not candidates:
        raise FileNotFoundError(f"No routing recommendation files found in {rec_dir}")
    return candidates[-1]


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_result(run_id: str, case_id: str) -> dict[str, Any]:
    result_path = settings.RESULTS_DIR / run_id / f"{case_id}_result.json"
    if not result_path.exists():
        raise FileNotFoundError(f"Result file not found: {result_path}")
    return json.loads(result_path.read_text(encoding="utf-8"))


def _find_snapshot(result: dict[str, Any], snapshot_id: str) -> dict[str, Any]:
    for snapshot in result.get("decision_snapshots", []) or []:
        if str(snapshot.get("snapshot_id", "")).strip() == snapshot_id:
            return snapshot
    raise KeyError(f"Snapshot not found: {snapshot_id}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run routing replay batch from a generated recommendation file."
    )
    parser.add_argument(
        "--recommendation-path",
        default="",
        help="Path to routing recommendation json. Defaults to latest recommendation file.",
    )
    parser.add_argument(
        "--replay-prefix",
        default="routing_recommendation_batch",
        help="Prefix for replay run ids and summary naming.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional max number of recommended rows to replay.",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=settings.MAX_TURNS,
        help="Max turns to use during replay. Defaults to current MAX_TURNS setting.",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        help="Only replay recommendations whose score is at least this value.",
    )
    parser.add_argument(
        "--bucket",
        choices=["all", "priority_replay", "review_candidate", "low_priority"],
        default="all",
        help="Optional priority bucket filter from the recommendation file.",
    )
    parser.add_argument(
        "--review-subbucket",
        choices=["all", "review_high", "review_low"],
        default="all",
        help="Optional review subbucket filter. Applies only to review_candidate rows.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    recommendation_path = (
        Path(str(args.recommendation_path).strip())
        if str(args.recommendation_path).strip()
        else _get_latest_recommendation()
    )
    recommendation = _load_json(recommendation_path)
    source_run_id = str(recommendation.get("source_run_id", "")).strip()
    replay_prefix = str(args.replay_prefix).strip() or "routing_recommendation_batch"
    max_turns = int(args.max_turns)
    limit = max(int(args.limit or 0), 0)
    min_score = float(args.min_score or 0.0)
    bucket = str(args.bucket).strip()
    review_subbucket = str(args.review_subbucket).strip()
    case_map = _case_map()

    rows: list[dict[str, Any]] = []
    replay_index = 0
    for row in recommendation.get("rows", []) or []:
        if limit and replay_index >= limit:
            break

        recommendation_block = dict(row.get("recommendation", {}) or {})
        recommendation_score = float(recommendation_block.get("score", 0.0) or 0.0)
        priority_bucket = str(row.get("priority_bucket", "")).strip() or "low_priority"
        if bucket != "all" and priority_bucket != bucket:
            continue
        row_review_subbucket = str(row.get("review_subbucket", "")).strip()
        if review_subbucket != "all":
            if priority_bucket != "review_candidate" or row_review_subbucket != review_subbucket:
                continue
        if recommendation_score < min_score:
            continue

        case_id = str(row.get("case_id", "")).strip()
        if not case_id:
            continue
        case = case_map.get(case_id)
        if not case:
            continue

        snapshot_id = str(recommendation_block.get("snapshot_id", "")).strip()
        selected_action = dict(recommendation_block.get("selected_action", {}) or {})
        if not snapshot_id or not str(selected_action.get("type", "")).strip():
            continue

        result = _load_result(source_run_id, case_id)
        snapshot = _find_snapshot(result, snapshot_id)
        replay_index += 1
        replay_run_id = f"{replay_prefix}_{replay_index:02d}"
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

        rows.append(
            {
                "replay_run_id": replay_run_id,
                "case_id": case_id,
                "snapshot_id": snapshot_id,
                "snapshot_node": str(recommendation_block.get("snapshot_node", "")).strip(),
                "selected_action": selected_action,
                "recommendation_score": recommendation_score,
                "priority_bucket": priority_bucket,
                "review_subbucket": row_review_subbucket,
                "recommendation_reasons": list(recommendation_block.get("reasons", []) or []),
                "comparison": comparison,
                "predicted_diagnosis": str(row.get("predicted_diagnosis", "")).strip(),
                "predicted_department": str(row.get("predicted_department", "")).strip(),
                "replay_diagnosis": str(replay_result.get("predicted_diagnosis", "")).strip(),
                "replay_department": str(replay_result.get("predicted_department", "")).strip(),
            }
        )
        print(
            f"{replay_run_id} | {case_id} | score={recommendation_score} | "
            f"improved={comparison.get('improved', False)} | reward_delta={comparison.get('reward_delta', 0.0)}"
        )

    summary = {
        "source_run_id": source_run_id,
        "source_recommendation_path": str(recommendation_path),
        "bucket": bucket,
        "review_subbucket": review_subbucket,
        "min_score": min_score,
        "replay_count": len(rows),
        "improved_count": sum(1 for row in rows if bool((row.get("comparison", {}) or {}).get("improved", False))),
        "rows": rows,
    }

    summary_dir = settings.WHAT_IF_DIR / "batch_summaries"
    summary_dir.mkdir(parents=True, exist_ok=True)
    summary_path = summary_dir / f"{replay_prefix}_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"summary_path={summary_path}")


if __name__ == "__main__":
    main()
