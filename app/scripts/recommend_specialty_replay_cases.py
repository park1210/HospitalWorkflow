from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
import re

from app.config import settings
from app.utils.what_if_recommendation_policy import get_specialty_recommendation_policy


SPECIALTY_REC_CONFIG = get_specialty_recommendation_policy()


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


def _get_latest_specialty_action_priors() -> dict[str, dict[str, float]]:
    dataset_dir = settings.WHAT_IF_DIR / "datasets"
    candidates = sorted(path for path in dataset_dir.glob("specialty*_dataset*.jsonl") if path.is_file())
    if not candidates:
        return {}
    latest = candidates[-1]
    priors: dict[str, dict[str, float]] = {}
    for raw_line in latest.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        record = json.loads(line)
        dept = str((record.get("original_result", {}) or {}).get("department", "")).strip()
        action_type = str((record.get("selected_action", {}) or {}).get("type", "")).strip()
        snapshot_node = str(record.get("snapshot_node", "")).strip()
        if not dept or not action_type or not snapshot_node:
            continue
        key = f"{dept}|{snapshot_node}|{action_type}"
        bucket = priors.setdefault(key, {"count": 0.0, "improved_count": 0.0})
        bucket["count"] += 1.0
        if bool(record.get("improved", False)):
            bucket["improved_count"] += 1.0
    for key, bucket in priors.items():
        count = float(bucket.get("count", 0.0) or 0.0)
        improved = float(bucket.get("improved_count", 0.0) or 0.0)
        bucket["improved_rate"] = round(improved / count, 4) if count else 0.0
    return priors


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


def _specialty_snapshots(result: dict[str, Any]) -> list[dict[str, Any]]:
    snapshots = [
        snapshot
        for snapshot in (result.get("decision_snapshots", []) or [])
        if str(snapshot.get("node", "")).strip() in {"specialty_next_step", "specialty_finalize"}
    ]
    node_priority = {"specialty_next_step": 0, "specialty_finalize": 1}
    return sorted(
        snapshots,
        key=lambda item: (
            int(item.get("turn_index", 0) or 0),
            node_priority.get(str(item.get("node", "")).strip(), 9),
        ),
    )


def _normalize_candidate_text(text: str) -> str:
    lowered = str(text or "").strip().lower()
    cleaned = re.sub(r"[^a-z0-9\s]", " ", lowered)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _token_set(text: str) -> set[str]:
    normalized = _normalize_candidate_text(text)
    if not normalized:
        return set()
    return {token for token in normalized.split() if token not in {"possible", "probable", "suspected", "acute", "chronic"}}


def _is_same_family_candidate(base_text: str, candidate_text: str) -> bool:
    base_tokens = _token_set(base_text)
    candidate_tokens = _token_set(candidate_text)
    if not base_tokens or not candidate_tokens:
        return False
    overlap = base_tokens & candidate_tokens
    if overlap and (len(overlap) >= min(len(base_tokens), len(candidate_tokens))):
        return True
    normalized_base = _normalize_candidate_text(base_text)
    normalized_candidate = _normalize_candidate_text(candidate_text)
    return normalized_base in normalized_candidate or normalized_candidate in normalized_base


def _find_action(snapshot: dict[str, Any], action_type: str) -> dict[str, str] | None:
    for option in snapshot.get("alternatives", []) or []:
        option_type = str(option.get("type", "")).strip()
        if option_type != action_type:
            continue
        return {
            "type": option_type,
            "target": str(option.get("target", "")).strip(),
        }
    return None


def _candidate_count(snapshot: dict[str, Any]) -> int:
    metadata = dict(snapshot.get("metadata", {}) or {})
    candidates = metadata.get("llm_candidate_diagnoses", []) or []
    return len([item for item in candidates if str(item).strip()])


def _candidate_profile(snapshot: dict[str, Any], current_diagnosis: str) -> dict[str, int]:
    metadata = dict(snapshot.get("metadata", {}) or {})
    raw_candidates = [str(item).strip() for item in (metadata.get("llm_candidate_diagnoses", []) or []) if str(item).strip()]
    non_generic_candidates = [item for item in raw_candidates if not _is_generic_diagnosis(item)]
    same_family = [item for item in non_generic_candidates if _is_same_family_candidate(current_diagnosis, item)]
    divergent = [item for item in non_generic_candidates if item not in same_family]
    return {
        "raw_count": len(raw_candidates),
        "non_generic_count": len(non_generic_candidates),
        "same_family_count": len(same_family),
        "divergent_count": len(divergent),
    }


def _build_recommendation(snapshot: dict[str, Any], action_priors: dict[str, dict[str, float]]) -> dict[str, Any] | None:
    cfg = SPECIALTY_REC_CONFIG
    node = str(snapshot.get("node", "")).strip()
    metadata = dict(snapshot.get("metadata", {}) or {})
    proposed_action = dict(snapshot.get("proposed_action", {}) or {})
    working = str(metadata.get("working_diagnosis", "")).strip()
    refined = str(metadata.get("refined_diagnosis", "")).strip()
    current_diagnosis = refined or working
    objective_count = int(metadata.get("objective_findings_count", 0) or 0)
    candidate_count = _candidate_count(snapshot)
    candidate_profile = _candidate_profile(snapshot, current_diagnosis)
    suggested_next_test = str(metadata.get("suggested_next_test", "")).strip()
    can_ask_patient = bool(metadata.get("can_ask_patient", False))
    is_generic = _is_generic_diagnosis(current_diagnosis)

    diagnose_now = _find_action(snapshot, "diagnose_now")
    request_test = _find_action(snapshot, "request_test")
    refine_again = _find_action(snapshot, "refine_again")

    score = 0.0
    reasons: list[str] = []
    selected_action: dict[str, str] | None = None

    if node == "specialty_finalize":
        if refine_again and is_generic and candidate_profile["non_generic_count"] >= 1:
            selected_action = refine_again
            score += float(cfg.get("finalize_generic_refine_bonus", 3.0) or 3.0)
            reasons.append("Multiple specialty candidates remain at finalize, so one more refinement pass may recover an exact diagnosis.")
        elif refine_again and candidate_profile["divergent_count"] >= 1:
            selected_action = refine_again
            score += float(cfg.get("finalize_divergent_refine_bonus", 2.0) or 2.0)
            reasons.append("A divergent exact specialty candidate remains unresolved at finalize.")
        elif request_test and suggested_next_test:
            selected_action = request_test
            score += float(cfg.get("finalize_request_test_bonus", 2.5) or 2.5)
            reasons.append("A specialty-priority follow-up test is still available at finalize.")
        elif diagnose_now and is_generic and objective_count == 0:
            selected_action = diagnose_now
            score += float(cfg.get("finalize_generic_diagnose_bonus", 1.0) or 1.0)
            reasons.append("Finalize remains generic without objective support, so a decisive diagnosis branch is worth probing.")
    elif node == "specialty_next_step":
        if request_test and suggested_next_test:
            selected_action = request_test
            score += float(cfg.get("next_step_request_test_bonus", 3.0) or 3.0)
            reasons.append("A targeted specialty test is still available before finalization.")
        elif diagnose_now and is_generic and not suggested_next_test and (objective_count > 0 or candidate_profile["non_generic_count"] > 0):
            selected_action = diagnose_now
            score += float(cfg.get("next_step_generic_diagnose_bonus", 2.5) or 2.5)
            reasons.append("The specialty path is still generic and no stronger test cue is available, so early commit may outperform extra questioning.")
        elif refine_again and candidate_count >= 2:
            selected_action = refine_again
            score += float(cfg.get("next_step_refine_bonus", 2.0) or 2.0)
            reasons.append("Candidate ambiguity is still high before finalization.")

    if not selected_action:
        return None

    department = str(metadata.get("department", "")).strip()
    action_prior_key = f"{department}|{node}|{selected_action.get('type', '')}"
    action_prior = dict(action_priors.get(action_prior_key, {}) or {})
    prior_count = int(action_prior.get("count", 0) or 0)
    prior_rate = float(action_prior.get("improved_rate", 0.0) or 0.0)

    if is_generic:
        score += float(cfg.get("generic_bonus", 1.0) or 1.0)
        reasons.append("Current specialty diagnosis is still generic.")
    if objective_count >= 2:
        score += float(cfg.get("objective_ready_bonus", 0.5) or 0.5)
        reasons.append("Objective evidence is already substantial.")
    if candidate_profile["divergent_count"] >= 1:
        score += float(cfg.get("divergent_candidate_bonus", 0.5) or 0.5)
        reasons.append("The candidate set includes a materially different exact alternative.")
    if candidate_profile["same_family_count"] >= 1 and candidate_profile["divergent_count"] == 0:
        score -= float(cfg.get("same_family_only_penalty", 1.0) or 1.0)
        reasons.append("The candidate set is dominated by same-family label variants, so replay value is lower.")
    if can_ask_patient and str(proposed_action.get("type", "")).strip() == "ask_patient":
        score += float(cfg.get("ask_loop_bonus", 0.25) or 0.25)
        reasons.append("The current policy still prefers another question, so replaying a non-question branch may reduce repetitive interviewing.")

    strong_prior_rate_min = float(cfg.get("strong_prior_rate_min", 0.67) or 0.67)
    weak_prior_rate_max = float(cfg.get("weak_prior_rate_max", 0.34) or 0.34)
    weak_prior_count_min = int(cfg.get("weak_prior_count_min", 2) or 2)
    if prior_count >= 1 and prior_rate >= strong_prior_rate_min:
        score += float(cfg.get("strong_prior_bonus", 0.75) or 0.75)
        reasons.append("This specialty action pattern has already shown strong replay recovery in prior runs.")
    elif prior_count >= weak_prior_count_min and prior_rate <= weak_prior_rate_max:
        score -= float(cfg.get("weak_prior_penalty", 0.75) or 0.75)
        reasons.append("This specialty action pattern has shown weak prior replay recovery, so it stays conservative.")

    if score < float(cfg.get("min_recommendation_score", 3.0) or 3.0):
        return None

    return {
        "snapshot_id": str(snapshot.get("snapshot_id", "")).strip(),
        "snapshot_node": node,
        "turn_index": int(snapshot.get("turn_index", 0) or 0),
        "selected_action": selected_action,
        "score": round(score, 2),
        "reasons": reasons,
        "current_specialty_diagnosis": current_diagnosis,
        "objective_findings_count": objective_count,
        "candidate_count": candidate_count,
        "candidate_profile": candidate_profile,
        "suggested_next_test": suggested_next_test,
        "action_prior_key": action_prior_key,
        "action_prior": action_prior,
        "generic_flag": is_generic,
        "objective_ready_flag": objective_count >= 2,
        "has_divergent_candidate": candidate_profile["divergent_count"] >= 1,
        "same_family_only_flag": candidate_profile["same_family_count"] >= 1 and candidate_profile["divergent_count"] == 0,
        "ask_loop_flag": can_ask_patient and str(proposed_action.get("type", "")).strip() == "ask_patient",
        "prior_supported_pattern": prior_count >= 1 and prior_rate >= strong_prior_rate_min,
        "prior_known_pattern": prior_count >= 1,
    }


def _best_recommendation(result: dict[str, Any], action_priors: dict[str, dict[str, float]]) -> dict[str, Any] | None:
    recommendations = []
    for snapshot in _specialty_snapshots(result):
        recommendation = _build_recommendation(snapshot, action_priors)
        if recommendation:
            recommendations.append(recommendation)
    if not recommendations:
        return None
    recommendations.sort(
        key=lambda item: (
            -float(item.get("score", 0.0) or 0.0),
            int(item.get("turn_index", 0) or 0),
        )
    )
    return recommendations[0]


def _priority_bucket(recommendation: dict[str, Any]) -> str:
    cfg = SPECIALTY_REC_CONFIG
    score = float(recommendation.get("score", 0.0) or 0.0)
    prior_supported = bool(recommendation.get("prior_supported_pattern", False))
    has_divergent = bool(recommendation.get("has_divergent_candidate", False))
    objective_ready = bool(recommendation.get("objective_ready_flag", False))
    if score >= float(cfg.get("priority_score_min", 4.0) or 4.0) and (prior_supported or (has_divergent and objective_ready)):
        return "priority_replay"
    if score >= float(cfg.get("min_recommendation_score", 3.0) or 3.0):
        return "review_candidate"
    return "low_priority"


def _review_subbucket(recommendation: dict[str, Any], priority_bucket: str) -> str:
    cfg = SPECIALTY_REC_CONFIG
    if priority_bucket != "review_candidate":
        return ""
    score = float(recommendation.get("score", 0.0) or 0.0)
    prior_known = bool(recommendation.get("prior_known_pattern", False))
    has_divergent = bool(recommendation.get("has_divergent_candidate", False))
    objective_ready = bool(recommendation.get("objective_ready_flag", False))
    same_family_only = bool(recommendation.get("same_family_only_flag", False))
    ask_loop = bool(recommendation.get("ask_loop_flag", False))

    if (
        score >= float(cfg.get("review_high_score_min", 3.5) or 3.5)
        and not same_family_only
        and (prior_known or has_divergent or (objective_ready and ask_loop))
    ):
        return "review_high"
    return "review_low"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Recommend specialty same-department replay candidates from a completed run."
    )
    parser.add_argument(
        "--run-id",
        default="",
        help="Source run id under outputs/results. Defaults to latest run.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of recommended cases to keep.",
    )
    parser.add_argument(
        "--include-department-incorrect",
        action="store_true",
        help="Include cases whose department prediction was also incorrect. Default focuses on same-department misses.",
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
    include_department_incorrect = bool(args.include_department_incorrect)
    limit = max(int(args.limit or 0), 0)
    action_priors = _get_latest_specialty_action_priors()

    rows: list[dict[str, Any]] = []
    for result in _iter_results(run_id):
        diagnosis_correct = bool(result.get("diagnosis_correct", False))
        department_correct = bool(result.get("department_correct", False))
        if diagnosis_correct:
            continue
        if not include_department_incorrect and not department_correct:
            continue

        recommendation = _best_recommendation(result, action_priors)
        if not recommendation:
            continue

        rows.append(
            {
                "case_id": str(result.get("case_id", "")).strip(),
                "predicted_diagnosis": str(result.get("predicted_diagnosis", "")).strip(),
                "predicted_department": str(result.get("predicted_department", "")).strip(),
                "ground_truth": str(result.get("ground_truth", "")).strip(),
                "ground_truth_department": str(result.get("ground_truth_department", "")).strip(),
                "department_correct": department_correct,
                "diagnosis_correct": diagnosis_correct,
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

    bucket_summary: dict[str, int] = {
        "priority_replay": sum(1 for row in rows if row.get("priority_bucket") == "priority_replay"),
        "review_candidate": sum(1 for row in rows if row.get("priority_bucket") == "review_candidate"),
        "low_priority": sum(1 for row in rows if row.get("priority_bucket") == "low_priority"),
    }
    review_subbucket_summary: dict[str, int] = {
        "review_high": sum(1 for row in rows if row.get("review_subbucket") == "review_high"),
        "review_low": sum(1 for row in rows if row.get("review_subbucket") == "review_low"),
    }

    summary = {
        "source_run_id": run_id,
        "same_department_focus": not include_department_incorrect,
        "recommended_case_count": len(rows),
        "bucket_summary": bucket_summary,
        "review_subbucket_summary": review_subbucket_summary,
        "rows": rows,
    }

    output_dir = settings.WHAT_IF_DIR / "recommendations"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_name = str(args.output_name).strip() or f"specialty_replay_recommendations_{run_id}.json"
    output_path = output_dir / output_name
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"source_run_id={run_id}")
    print(f"recommended_case_count={len(rows)}")
    for row in rows[: min(5, len(rows))]:
        rec = dict(row.get("recommendation", {}) or {})
        action = dict(rec.get("selected_action", {}) or {})
        print(
            f"{row['case_id']} | node={rec.get('snapshot_node')} | score={rec.get('score')} | "
            f"action={action.get('type')}:{action.get('target', '')}"
        )
    print(f"output_path={output_path}")


if __name__ == "__main__":
    main()
