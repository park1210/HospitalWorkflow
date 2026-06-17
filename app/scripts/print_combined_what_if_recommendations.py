from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.config import settings


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Combined recommendation file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_combined() -> Path:
    rec_dir = settings.WHAT_IF_DIR / "recommendations"
    candidates = sorted(path for path in rec_dir.glob("combined_what_if_recommendations_*.json") if path.is_file())
    if not candidates:
        raise FileNotFoundError(f"No combined recommendation files found in {rec_dir}")
    return candidates[-1]


def _short_reasons(reasons: list[str], limit: int = 2) -> str:
    trimmed = [str(item).strip() for item in reasons if str(item).strip()]
    return " | ".join(trimmed[:limit])


def _rows(payload: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    rows = list(payload.get("rows", []) or [])
    if limit > 0:
        rows = rows[:limit]
    return rows


def _render_markdown(payload: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Combined What-If Recommendations",
        "",
        f"- source_run_id: `{payload.get('source_run_id', '')}`",
        f"- case_recommendation_count: `{payload.get('case_recommendation_count', 0)}`",
        "",
        "| case_id | type | bucket | score | predicted_dept | action | note |",
        "|---|---|---|---:|---|---|---|",
    ]
    for row in rows:
        action = dict(row.get("selected_action", {}) or {})
        bucket = str(row.get("priority_bucket", "")).strip()
        review = str(row.get("review_subbucket", "")).strip()
        bucket_text = f"{bucket}/{review}" if review else bucket
        lines.append(
            f"| {row.get('case_id', '')} | {row.get('type', '')} | {bucket_text} | "
            f"{float(row.get('score', 0.0) or 0.0):.2f} | {row.get('predicted_department', '')} | "
            f"{action.get('type', '')}:{action.get('target', '')} | "
            f"{_short_reasons(list(row.get('reasons', []) or []))} |"
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Print the combined routing + specialty what-if recommendation list.")
    parser.add_argument(
        "--recommendation-path",
        default="",
        help="Optional combined recommendation path. Defaults to latest combined file.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=12,
        help="Maximum number of rows to print.",
    )
    parser.add_argument(
        "--markdown-out",
        default="",
        help="Optional markdown output path.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    recommendation_path = (
        Path(str(args.recommendation_path).strip())
        if str(args.recommendation_path).strip()
        else _latest_combined()
    )
    payload = _load_json(recommendation_path)
    rows = _rows(payload, int(args.limit))

    print(f"source_run_id={payload.get('source_run_id', '')}")
    print(f"case_recommendation_count={payload.get('case_recommendation_count', 0)}")
    print()
    header = "case_id | type | bucket | score | predicted_dept | action | note"
    print(header)
    print("-" * len(header))
    for row in rows:
        action = dict(row.get("selected_action", {}) or {})
        bucket = str(row.get("priority_bucket", "")).strip()
        review = str(row.get("review_subbucket", "")).strip()
        bucket_text = f"{bucket}/{review}" if review else bucket
        print(
            f"{row.get('case_id', '')} | {row.get('type', '')} | {bucket_text} | "
            f"{float(row.get('score', 0.0) or 0.0):.2f} | {row.get('predicted_department', '')} | "
            f"{action.get('type', '')}:{action.get('target', '')} | "
            f"{_short_reasons(list(row.get('reasons', []) or []))}"
        )

    markdown_out = str(args.markdown_out).strip()
    if markdown_out:
        markdown_path = Path(markdown_out)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(_render_markdown(payload, rows), encoding="utf-8")
        print()
        print(f"markdown_path={markdown_path}")


if __name__ == "__main__":
    main()
