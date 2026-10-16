"""Evaluate a saved run without re-running policies or calling an LLM."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.hospital_evaluation import evaluation_report, paired_comparison
from app.core.hospital_scheduler_state import HospitalSchedulerState


def evaluate_saved_run(path: Path, annotations_path: Path | None = None) -> dict:
    report = json.loads(path.read_text(encoding="utf-8-sig"))
    source = {c["case_id"]: c for c in report.get("source_cases", [])}
    if not source:
        raise ValueError("Saved run must include source_cases; do not infer missing gold data")
    snapshot = report["final_state"]
    if set(source) != set(snapshot["cases"]):
        raise ValueError("source_cases must cover exactly the saved state")
    if annotations_path:
        annotations = json.loads(annotations_path.read_text(encoding="utf-8-sig"))
        if not isinstance(annotations, dict) or set(annotations) - set(source):
            raise ValueError("Annotations must be an object keyed by existing case ids")
        for cid, annotation in annotations.items():
            if not isinstance(annotation, dict):
                raise ValueError("Each annotation must be an evaluation object")
            source[cid]["evaluation"] = {**source[cid].get("evaluation", {}), **annotation}
    state = HospitalSchedulerState.from_snapshot(snapshot, source)
    result = evaluation_report(state)
    result["annotation_provenance"] = {
        "source": "sidecar_after_run" if annotations_path else "saved_case_annotations",
        "note": "Require expert annotation fixed before policy comparison; retrospective input does not establish independence"}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--annotations", type=Path, help="Optional case_id -> evaluation annotation JSON")
    parser.add_argument("--compare-report", type=Path, help="Saved parallel run for paired comparison")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = evaluate_saved_run(args.report, args.annotations)
    if args.compare_report:
        result["paired_comparison"] = paired_comparison(result, evaluate_saved_run(args.compare_report, args.annotations))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(f"[EVALUATION] {args.output}")
    for group, metrics in result["groups"].items():
        print(group, {name: {"value": row["value"], "status": row["status"]} for name, row in metrics.items()})
    print("[VALIDITY] Demo-policy audit; independent clinical evaluation is not established.")


if __name__ == "__main__":
    main()
