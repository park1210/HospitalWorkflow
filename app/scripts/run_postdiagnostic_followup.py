"""Observe completed cases from a saved parallel run, without inference."""
import argparse
import json
from pathlib import Path

from app.core.postdiagnostic_followup import followup_from_summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--minutes", type=int, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    report = followup_from_summary(summary, args.minutes)
    destination = args.output or args.summary.parent / "postdiagnostic_followup.json"
    if destination.resolve() == args.summary.resolve():
        raise ValueError("Output must not overwrite the source summary")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[FOLLOWUP] cases={len(report['cases'])} skipped={len(report['skipped_cases'])} LLM calls=0 report={destination}")


if __name__ == "__main__":
    main()
