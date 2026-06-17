from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.config import settings


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


def _short_reasons(reasons: list[str], limit: int = 2) -> str:
    trimmed = [str(item).strip() for item in reasons if str(item).strip()]
    return " | ".join(trimmed[:limit])


def _routing_risk_note(recommendation: dict[str, Any]) -> str:
    risks: list[str] = []
    if not bool(recommendation.get("prior_known_transition", False)):
        risks.append("no prior support")
    if not bool(recommendation.get("objective_ready_flag", False)):
        risks.append("limited evidence")
    if bool(recommendation.get("no_prior_large_gap_flag", False)):
        risks.append("large gap")
    elif bool(recommendation.get("moderate_gap_flag", False)) and not bool(
        recommendation.get("prior_supported_transition", False)
    ):
        risks.append("moderate gap")
    if not risks:
        if bool(recommendation.get("low_gap_flag", False)):
            risks.append("low-gap but uncertain")
        else:
            risks.append("manual review")
    return ", ".join(risks[:2])


def _specialty_risk_note(recommendation: dict[str, Any]) -> str:
    risks: list[str] = []
    if bool(recommendation.get("same_family_only_flag", False)):
        risks.append("same-family only")
    if not bool(recommendation.get("prior_known_pattern", False)):
        risks.append("no prior pattern")
    if not bool(recommendation.get("objective_ready_flag", False)):
        risks.append("limited evidence")
    if not risks:
        if bool(recommendation.get("has_divergent_candidate", False)):
            risks.append("divergent candidate")
        else:
            risks.append("manual review")
    return ", ".join(risks[:2])


def _collect_rows(payload: dict[str, Any], bucket: str, limit: int) -> list[dict[str, Any]]:
    rows = [row for row in payload.get("rows", []) or [] if str(row.get("priority_bucket", "")).strip() == bucket]
    if limit > 0:
        rows = rows[:limit]
    return rows


def _render_markdown(kind: str, payload: dict[str, Any], bucket: str, rows: list[dict[str, Any]]) -> str:
    lines = [
        f"# {kind.title()} What-If {bucket}",
        "",
        f"- source_run_id: `{payload.get('source_run_id', '')}`",
        f"- bucket: `{bucket}`",
        f"- row_count: `{len(rows)}`",
        "",
    ]
    if not rows:
        lines.append("No rows matched the requested bucket.")
        return "\n".join(lines)

    if kind == "routing":
        lines.extend(
            [
                "| case_id | score | action | predicted_dept | gold_dept | gap | review | risk | note |",
                "|---|---:|---|---|---|---:|---|---|---|",
            ]
        )
        for row in rows:
            recommendation = dict(row.get("recommendation", {}) or {})
            action = dict(recommendation.get("selected_action", {}) or {})
            score = float(recommendation.get("score", 0.0) or 0.0)
            note = _short_reasons(list(recommendation.get("reasons", []) or []))
            risk = _routing_risk_note(recommendation)
            review_subbucket = str(row.get("review_subbucket", "")).strip() or "-"
            lines.append(
                f"| {row.get('case_id', '')} | {score:.2f} | "
                f"{action.get('type', '')}:{action.get('target', '')} | "
                f"{row.get('predicted_department', '')} | "
                f"{row.get('ground_truth_department', '')} | "
                f"{recommendation.get('score_gap', '')} | {review_subbucket} | {risk} | {note} |"
            )
    else:
        lines.extend(
            [
                "| case_id | score | action | predicted_diag | dept | node | review | risk | note |",
                "|---|---:|---|---|---|---|---|---|---|",
            ]
        )
        for row in rows:
            recommendation = dict(row.get("recommendation", {}) or {})
            action = dict(recommendation.get("selected_action", {}) or {})
            score = float(recommendation.get("score", 0.0) or 0.0)
            note = _short_reasons(list(recommendation.get("reasons", []) or []))
            risk = _specialty_risk_note(recommendation)
            review_subbucket = str(row.get("review_subbucket", "")).strip() or "-"
            lines.append(
                f"| {row.get('case_id', '')} | {score:.2f} | "
                f"{action.get('type', '')}:{action.get('target', '')} | "
                f"{row.get('predicted_diagnosis', '')} | "
                f"{row.get('predicted_department', '')} | "
                f"{recommendation.get('snapshot_node', '')} | {review_subbucket} | {risk} | {note} |"
            )
    return "\n".join(lines)


def _print_rows(kind: str, payload: dict[str, Any], bucket: str, rows: list[dict[str, Any]]) -> None:

    print(f"type={kind}")
    print(f"source_run_id={payload.get('source_run_id', '')}")
    print(f"bucket={bucket}")
    print(f"row_count={len(rows)}")
    print()

    if not rows:
        print("No rows matched the requested bucket.")
        return

    if kind == "routing":
        header = "case_id | score | action | predicted_dept | gold_dept | gap | review | risk | note"
    else:
        header = "case_id | score | action | predicted_diag | dept | node | review | risk | note"
    print(header)
    print("-" * len(header))

    for row in rows:
        recommendation = dict(row.get("recommendation", {}) or {})
        action = dict(recommendation.get("selected_action", {}) or {})
        score = float(recommendation.get("score", 0.0) or 0.0)
        note = _short_reasons(list(recommendation.get("reasons", []) or []))
        if kind == "routing":
            risk = _routing_risk_note(recommendation)
            review_subbucket = str(row.get("review_subbucket", "")).strip() or "-"
            print(
                f"{row.get('case_id', '')} | "
                f"{score:.2f} | "
                f"{action.get('type', '')}:{action.get('target', '')} | "
                f"{row.get('predicted_department', '')} | "
                f"{row.get('ground_truth_department', '')} | "
                f"{recommendation.get('score_gap', '')} | "
                f"{review_subbucket} | "
                f"{risk} | "
                f"{note}"
            )
        else:
            risk = _specialty_risk_note(recommendation)
            review_subbucket = str(row.get("review_subbucket", "")).strip() or "-"
            print(
                f"{row.get('case_id', '')} | "
                f"{score:.2f} | "
                f"{action.get('type', '')}:{action.get('target', '')} | "
                f"{row.get('predicted_diagnosis', '')} | "
                f"{row.get('predicted_department', '')} | "
                f"{recommendation.get('snapshot_node', '')} | "
                f"{review_subbucket} | "
                f"{risk} | "
                f"{note}"
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print compact tables for routing/specialty what-if recommendation buckets."
    )
    parser.add_argument(
        "--type",
        choices=["routing", "specialty"],
        required=True,
        help="Which recommendation type to print.",
    )
    parser.add_argument(
        "--recommendation-path",
        default="",
        help="Optional explicit recommendation file. Defaults to latest file of the chosen type.",
    )
    parser.add_argument(
        "--bucket",
        choices=["priority_replay", "review_candidate", "low_priority"],
        default="review_candidate",
        help="Which bucket to print.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of rows to print.",
    )
    parser.add_argument(
        "--markdown-out",
        default="",
        help="Optional markdown output path. If omitted, nothing is written.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    kind = str(args.type).strip()
    recommendation_path = (
        Path(str(args.recommendation_path).strip())
        if str(args.recommendation_path).strip()
        else _latest_recommendation(kind)
    )
    payload = _load_json(recommendation_path)
    bucket = str(args.bucket).strip()
    rows = _collect_rows(payload, bucket, int(args.limit))
    _print_rows(kind, payload, bucket, rows)

    markdown_out = str(args.markdown_out).strip()
    if markdown_out:
        markdown_path = Path(markdown_out)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(_render_markdown(kind, payload, bucket, rows), encoding="utf-8")
        print()
        print(f"markdown_path={markdown_path}")


if __name__ == "__main__":
    main()
