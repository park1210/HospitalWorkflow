"""Run Chapter 7 workload/resource experiments without a viewer or LLM."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from app.config import settings
from app.core.hospital_experiments import run_experiments, provenance, render_summary
from app.data.demo_scenario_loader import load_demo_scenario_cases
from app.data.loader import load_raw_cases
from app.data.transform import transform_case


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-file", required=True, type=Path)
    parser.add_argument("--plan", type=Path, default=settings.PROJECT_ROOT / "app/data/hospital_experiment_plan.example.json")
    parser.add_argument("--annotations", type=Path, help="case_id -> evaluation annotation; fixed before all conditions")
    parser.add_argument("--output-dir", required=True, type=Path, help="New directory; existing results are never overwritten")
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("Output directory already exists; choose a new experiment directory")
    # Explicit path takes precedence over USE_PROCESSED_CASES and other UI defaults.
    if args.scenario_file.suffix.lower() == ".json":
        cases, _ = load_demo_scenario_cases(args.scenario_file)
    else:
        cases = [transform_case(case, i) for i, case in enumerate(load_raw_cases(args.scenario_file))]
    if args.annotations:
        annotations = json.loads(args.annotations.read_text(encoding="utf-8-sig"))
        if not isinstance(annotations, dict) or set(annotations) - {c["case_id"] for c in cases}:
            raise ValueError("Annotations must refer only to existing case ids")
        for case in cases:
            annotation = annotations.get(case["case_id"], {})
            if not isinstance(annotation, dict):
                raise ValueError("Each annotation must be an object")
            case["evaluation"] = {**case.get("evaluation", {}), **annotation}
    plan = json.loads(args.plan.read_text(encoding="utf-8-sig"))
    code_provenance = provenance(settings.PROJECT_ROOT)
    result = run_experiments(cases, plan)
    result["provenance"] = code_provenance
    result["metric_provenance"] = json.loads(
        (settings.PROJECT_ROOT / "app/data/hospital_metric_provenance.json").read_text(encoding="utf-8"))
    result["input_files"] = {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in (args.scenario_file, args.plan, args.annotations) if p}
    args.output_dir.mkdir(parents=True, exist_ok=False)
    def save(name, data):
        (args.output_dir / name).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    save("experiment_manifest.json", {k: v for k, v in result.items() if k != "runs"})
    save("readiness.json", result["readiness"])
    for run in result["runs"]:
        run["experiment"]["source_digest"] = code_provenance["source_digest"]
        save(run["run_id"] + ".json", run)
    (args.output_dir / "summary.md").write_text(render_summary(result), encoding="utf-8")
    print(f"[EXPERIMENTS] {len(result['runs'])} runs, {len(result['skipped'])} skipped -> {args.output_dir}")
    print("[VALIDITY] Deterministic demo workflow experiments; no independent clinical/model performance claim.")


if __name__ == "__main__":
    main()
