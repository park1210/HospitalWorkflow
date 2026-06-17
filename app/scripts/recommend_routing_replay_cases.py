from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.config import settings
from app.utils.department_catalog import normalize_department
from app.utils.what_if_recommendation_policy import get_routing_recommendation_policy


ROUTING_REC_CONFIG = get_routing_recommendation_policy()


def _get_latest_run_id() -> str:
    run_dirs = sorted(path.name for path in settings.RESULTS_DIR.iterdir() if path.is_dir())
    if not run_dirs:
        raise FileNotFoundError(f"No run directories found in {settings.RESULTS_DIR}")
    return run_dirs[-1]


def _iter_results(run_id: str) -> list[dict[str, Any]]:
    run_dir = settings.RESULTS_DIR / run_id
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")
    rows: list[dict[str, Any]] = []
    for result_path in sorted(run_dir.glob("case_*_result.json")):
        rows.append(json.loads(result_path.read_text(encoding="utf-8")))
    return rows


def _is_generic_diagnosis(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return True
    prefixes = (
        "possible ",
        "probable ",
        "suspected ",
        "undifferentiated ",
        "generic ",
    )
    generic_markers = (
        "process",
        "complaint",
        "problem",
        "syndrome",
        "condition",
        "disorder",
        "compromise",
    )
    if normalized.startswith(prefixes):
        return True
    return any(marker in normalized for marker in generic_markers)


def _routing_snapshot(result: dict[str, Any]) -> dict[str, Any] | None:
    snapshots = [
        snapshot
        for snapshot in (result.get("decision_snapshots", []) or [])
        if str(snapshot.get("node", "")).strip() == "er_routing"
    ]
    if not snapshots:
        return None
    return sorted(snapshots, key=lambda item: int(item.get("turn_index", 0) or 0))[-1]


def _direct_reroute_options(snapshot: dict[str, Any], predicted_department: str) -> list[str]:
    options = []
    proposed = dict(snapshot.get("proposed_action", {}) or {})
    proposed_target = normalize_department(str(proposed.get("target", "")).strip(), default="")
    for option in snapshot.get("alternatives", []) or []:
        if str(option.get("type", "")).strip() != "handoff_department":
            continue
        raw_target = str(option.get("target", "")).strip()
        target = normalize_department(raw_target, default="")
        if not target or target == proposed_target or target == predicted_department:
            continue
        if raw_target not in options:
            options.append(raw_target)
    return options


def _score_gap(snapshot: dict[str, Any], original_department: str, target_department: str) -> float:
    metadata = dict(snapshot.get("metadata", {}) or {})
    scores = dict(metadata.get("routing_scores", {}) or {})
    original_score = float(scores.get(original_department, 0.0) or 0.0)
    target_score = float(scores.get(target_department, 0.0) or 0.0)
    return round(abs(original_score - target_score), 4)


def _get_latest_transition_priors() -> dict[str, dict[str, float]]:
    dataset_dir = settings.WHAT_IF_DIR / "datasets"
    candidates = sorted(path for path in dataset_dir.glob("routing_*analysis.json") if path.is_file())
    if not candidates:
        return {}
    latest = candidates[-1]
    data = json.loads(latest.read_text(encoding="utf-8"))
    priors: dict[str, dict[str, float]] = {}
    for row in data.get("department_transition_summary", []) or []:
        key = str(row.get("transition", "")).strip()
        if not key:
            continue
        priors[key] = {
            "count": float(row.get("count", 0) or 0.0),
            "improved_rate": float(row.get("improved_rate", 0.0) or 0.0),
            "average_reward_delta": float(row.get("average_reward_delta", 0.0) or 0.0),
        }
    return priors


def _priority_bucket(recommendation: dict[str, Any]) -> str:
    cfg = ROUTING_REC_CONFIG
    score = float(recommendation.get("score", 0.0) or 0.0)
    raw_gap = recommendation.get("score_gap", None)
    score_gap = float(raw_gap) if raw_gap is not None else 99.0
    objective_count = int(recommendation.get("objective_findings_count", 0) or 0)
    working_diagnosis = str(recommendation.get("working_diagnosis", "")).strip()
    is_generic = _is_generic_diagnosis(working_diagnosis)
    prior = dict(recommendation.get("transition_prior", {}) or {})
    prior_rate = float(prior.get("improved_rate", 0.0) or 0.0)
    prior_count = int(prior.get("count", 0) or 0)

    if (
        is_generic
        and objective_count >= int(cfg.get("priority_objective_min", 2) or 2)
        and score_gap < float(cfg.get("priority_gap_max", 1.0) or 1.0)
        and score >= float(cfg.get("priority_score_min", 5.0) or 5.0)
        and prior_count >= int(cfg.get("priority_prior_count_min", 1) or 1)
        and prior_rate >= float(cfg.get("priority_prior_rate_min", 0.75) or 0.75)
    ):
        return "priority_replay"
    if score >= float(cfg.get("min_recommendation_score", 3.0) or 3.0):
        return "review_candidate"
    return "low_priority"


def _review_subbucket(recommendation: dict[str, Any], priority_bucket: str) -> str:
    cfg = ROUTING_REC_CONFIG
    if priority_bucket != "review_candidate":
        return ""
    prior_known = bool(recommendation.get("prior_known_transition", False))
    prior_supported = bool(recommendation.get("prior_supported_transition", False))
    low_gap = bool(recommendation.get("low_gap_flag", False))
    objective_ready = bool(recommendation.get("objective_ready_flag", False))
    large_gap = bool(recommendation.get("no_prior_large_gap_flag", False))
    score = float(recommendation.get("score", 0.0) or 0.0)
    raw_gap = recommendation.get("score_gap", None)
    score_gap = float(raw_gap) if raw_gap is not None else 99.0

    if (
        score >= float(cfg.get("review_high_score_min", 5.0) or 5.0)
        and objective_ready
        and not large_gap
        and (
            (prior_supported and score_gap < float(cfg.get("review_high_gap_max", 4.0) or 4.0))
            or (prior_known and low_gap)
        )
    ):
        return "review_high"
    return "review_low"


def _transition_key(original_department: str, target_department: str) -> str:
    return f"{original_department} -> {target_department}"


def _build_recommendation(
    result: dict[str, Any],
    snapshot: dict[str, Any],
    transition_priors: dict[str, dict[str, float]],
) -> dict[str, Any] | None:
    cfg = ROUTING_REC_CONFIG
    predicted_department = normalize_department(str(result.get("predicted_department", "")).strip(), default="")
    options = _direct_reroute_options(snapshot, predicted_department)
    if not options:
        return None

    metadata = dict(snapshot.get("metadata", {}) or {})
    working_diagnosis = str(metadata.get("working_diagnosis", "")).strip()
    objective_count = int(metadata.get("objective_findings_count", 0) or 0)
    is_generic = _is_generic_diagnosis(working_diagnosis)

    best_option: dict[str, Any] | None = None
    for raw_target in options:
        target_department = normalize_department(raw_target, default="")
        gap = _score_gap(snapshot, predicted_department, target_department)
        score = 0.0
        reasons: list[str] = []
        transition_key = _transition_key(predicted_department, target_department)
        transition_prior = dict(transition_priors.get(transition_key, {}) or {})
        prior_rate = float(transition_prior.get("improved_rate", 0.0) or 0.0)
        prior_count = int(transition_prior.get("count", 0) or 0)

        score += float(cfg.get("base_score", 2.0) or 2.0)
        reasons.append("A concrete alternative specialty is already present in the ER routing shortlist.")

        if is_generic:
            score += float(cfg.get("generic_bonus", 1.5) or 1.5)
            reasons.append("The ER working diagnosis is still generic.")
        if objective_count >= 2:
            score += float(cfg.get("objective_ready_bonus", 1.0) or 1.0)
            reasons.append("Objective evidence is already substantial.")
        if gap < float(cfg.get("priority_gap_max", 1.0) or 1.0):
            score += float(cfg.get("low_gap_bonus", 2.0) or 2.0)
            reasons.append("The top routing alternatives are very close in score, so reroute replay value is high.")
        elif gap < float(cfg.get("moderate_gap_upper", 3.0) or 3.0):
            score += float(cfg.get("moderate_gap_bonus", 1.0) or 1.0)
            reasons.append("The routing score gap is moderate, so the alternative remains plausible.")
        else:
            reasons.append("The routing score gap is large, so this alternative is lower-confidence.")

        if target_department in {"general_medicine", "internal_medicine"}:
            score -= float(cfg.get("fallback_department_penalty", 1.0) or 1.0)
            reasons.append("Fallback-style departments are lower-value replay targets than specific specialty alternatives.")

        if (
            prior_count >= int(cfg.get("priority_prior_count_min", 1) or 1)
            and prior_rate >= float(cfg.get("priority_prior_rate_min", 0.75) or 0.75)
        ):
            score += float(cfg.get("strong_prior_bonus", 1.5) or 1.5)
            reasons.append("This department transition has already shown strong replay recovery in prior routing analysis.")
        elif prior_count == 0:
            score -= float(cfg.get("no_prior_penalty", 1.0) or 1.0)
            reasons.append("This department transition has no established replay recovery history yet.")
        else:
            reasons.append("This department transition has mixed prior replay results, so it stays review-oriented.")

        moderate_gap_upper = float(cfg.get("moderate_gap_upper", 3.0) or 3.0)
        if prior_count == 0 and gap >= moderate_gap_upper:
            score -= float(cfg.get("large_gap_no_prior_penalty", 1.0) or 1.0)
            reasons.append("A large score gap without prior recovery support makes this a weak review candidate.")
        elif prior_count == 0 and gap >= float(cfg.get("priority_gap_max", 1.0) or 1.0):
            score -= float(cfg.get("moderate_gap_no_prior_penalty", 0.5) or 0.5)
            reasons.append("A moderate score gap without prior recovery support keeps this recommendation conservative.")

        if score < float(cfg.get("min_recommendation_score", 3.0) or 3.0):
            continue

        candidate = {
            "snapshot_id": str(snapshot.get("snapshot_id", "")).strip(),
            "snapshot_node": "er_routing",
            "turn_index": int(snapshot.get("turn_index", 0) or 0),
            "selected_action": {
                "type": "handoff_department",
                "target": raw_target,
            },
            "score": round(score, 2),
            "reasons": reasons,
            "working_diagnosis": working_diagnosis,
            "objective_findings_count": objective_count,
            "score_gap": gap,
            "routing_candidates": list(metadata.get("routing_candidates", []) or []),
            "routing_scores": dict(metadata.get("routing_scores", {}) or {}),
            "transition_key": transition_key,
            "transition_prior": transition_prior,
            "generic_flag": is_generic,
            "objective_ready_flag": objective_count >= 2,
            "low_gap_flag": gap < float(cfg.get("priority_gap_max", 1.0) or 1.0),
            "moderate_gap_flag": float(cfg.get("priority_gap_max", 1.0) or 1.0) <= gap < float(cfg.get("moderate_gap_upper", 3.0) or 3.0),
            "prior_supported_transition": (
                prior_count >= int(cfg.get("priority_prior_count_min", 1) or 1)
                and prior_rate >= float(cfg.get("priority_prior_rate_min", 0.75) or 0.75)
            ),
            "prior_known_transition": prior_count >= int(cfg.get("priority_prior_count_min", 1) or 1),
            "no_prior_large_gap_flag": prior_count == 0 and gap >= float(cfg.get("moderate_gap_upper", 3.0) or 3.0),
        }
        if not best_option or float(candidate["score"]) > float(best_option["score"]):
            best_option = candidate

    return best_option


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Recommend ER routing replay candidates from a completed run."
    )
    parser.add_argument(
        "--run-id",
        default="",
        help="Source run id under outputs/results. Defaults to latest run.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of recommended cases to keep.",
    )
    parser.add_argument(
        "--include-department-correct",
        action="store_true",
        help="Include cases whose department prediction was already correct.",
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

    run_id = str(args.run_id).strip() or _get_latest_run_id()
    include_department_correct = bool(args.include_department_correct)
    limit = max(int(args.limit or 0), 0)
    transition_priors = _get_latest_transition_priors()

    rows: list[dict[str, Any]] = []
    for result in _iter_results(run_id):
        if not include_department_correct and bool(result.get("department_correct", False)):
            continue
        snapshot = _routing_snapshot(result)
        if not snapshot:
            continue
        recommendation = _build_recommendation(result, snapshot, transition_priors)
        if not recommendation:
            continue
        rows.append(
            {
                "case_id": str(result.get("case_id", "")).strip(),
                "predicted_diagnosis": str(result.get("predicted_diagnosis", "")).strip(),
                "predicted_department": str(result.get("predicted_department", "")).strip(),
                "ground_truth": str(result.get("ground_truth", "")).strip(),
                "ground_truth_department": str(result.get("ground_truth_department", "")).strip(),
                "department_correct": bool(result.get("department_correct", False)),
                "diagnosis_correct": bool(result.get("diagnosis_correct", False)),
                "recommendation": recommendation,
            }
        )

    rows.sort(
        key=lambda item: (
            -float((item.get("recommendation", {}) or {}).get("score", 0.0) or 0.0),
            str(item.get("case_id", "")),
        )
    )
    if limit:
        rows = rows[:limit]

    for row in rows:
        recommendation = dict(row.get("recommendation", {}) or {})
        priority_bucket = _priority_bucket(recommendation)
        row["priority_bucket"] = priority_bucket
        row["review_subbucket"] = _review_subbucket(recommendation, priority_bucket)

    bucket_summary = {
        "priority_replay": sum(1 for row in rows if row.get("priority_bucket") == "priority_replay"),
        "review_candidate": sum(1 for row in rows if row.get("priority_bucket") == "review_candidate"),
        "low_priority": sum(1 for row in rows if row.get("priority_bucket") == "low_priority"),
    }
    review_subbucket_summary = {
        "review_high": sum(1 for row in rows if row.get("review_subbucket") == "review_high"),
        "review_low": sum(1 for row in rows if row.get("review_subbucket") == "review_low"),
    }

    summary = {
        "source_run_id": run_id,
        "department_incorrect_focus": not include_department_correct,
        "recommended_case_count": len(rows),
        "bucket_summary": bucket_summary,
        "review_subbucket_summary": review_subbucket_summary,
        "rows": rows,
    }

    output_dir = settings.WHAT_IF_DIR / "recommendations"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_name = str(args.output_name).strip() or f"routing_replay_recommendations_{run_id}.json"
    output_path = output_dir / output_name
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"source_run_id={run_id}")
    print(f"recommended_case_count={len(rows)}")
    for row in rows[: min(5, len(rows))]:
        rec = dict(row.get("recommendation", {}) or {})
        action = dict(rec.get("selected_action", {}) or {})
        print(
            f"{row['case_id']} | gap={rec.get('score_gap')} | score={rec.get('score')} | "
            f"action={action.get('type')}:{action.get('target', '')}"
        )
    print(f"output_path={output_path}")


if __name__ == "__main__":
    main()
