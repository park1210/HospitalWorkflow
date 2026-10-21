"""Fit routing/VoI artifacts from explicit training inputs; never calls an LLM.

Both models can be built together or separately. Missing data is an error,
not permission to generate clinical likelihoods or specialty success labels.
"""
import argparse
import hashlib
import json
from pathlib import Path

from app.core.agent_registry import AgentRegistry
from app.core.routing_utility import fit_utility
from app.core.voi_evaluation import fit_outcome_spec


def build_models(*, evaluation_cases, registry=None, routing_rows=None,
                 voi_spec=None, voi_rows=None, min_samples=2, min_observations=1, alpha=1.0):
    if not isinstance(evaluation_cases, list) or not evaluation_cases:
        raise ValueError("Nonempty held-out evaluation cases required")
    held_out = {c["longitudinal"]["patient_id"] for c in evaluation_cases}
    if any(not isinstance(p, str) or not p for p in held_out):
        raise ValueError("Evaluation patient IDs required")
    artifacts = {}
    if routing_rows is not None:
        if not registry or not isinstance(routing_rows, list) or not routing_rows:
            raise ValueError("Registry and actual specialty outcome rows required")
        if held_out & {r["patient_id"] for r in routing_rows}:
            raise ValueError("Routing train/evaluation patient overlap")
        for row in routing_rows:
            # Collection failures are availability failures, not diagnosis errors.
            if "audit" in row and (not row["audit"] or any(a.get("status") != "success" for a in row["audit"])):
                raise ValueError("Routing rows contain failed calls; recollect the complete probe")
            if "answer" in row and row["answer"] is None:
                raise ValueError("Routing row has no model answer")
        artifact = fit_utility(routing_rows, AgentRegistry(registry), min_samples=min_samples)
        groups = {}
        for row in routing_rows:
            groups.setdefault((row["patient_id"], row["decision_id"]), []).append(row)
        if len(groups) < min_samples:
            raise ValueError("Fewer training decisions than routing min_samples")
        if any(r["observation"] != group[0]["observation"] for group in groups.values() for r in group):
            raise ValueError("Routing candidates must share exactly the same public observation")
        if not any(s["tokens"] for s in artifact["samples"]):
            raise ValueError("Routing training observations have no retrievable tokens")
        artifacts["routing_utility"] = artifact
    elif registry is not None:
        raise ValueError("Registry supplied without routing rows")
    if voi_spec is not None or voi_rows is not None:
        if voi_spec is None or voi_rows is None:
            raise ValueError("Both probability-free VoI spec and observed training rows required")
        artifacts["voi_model"] = fit_outcome_spec(voi_spec, voi_rows, alpha,
            evaluation_patients=held_out, min_observations=min_observations)
    if not artifacts:
        raise ValueError("Supply routing training inputs and/or VoI training inputs")
    return artifacts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-cases", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    for name in ("registry", "routing-data", "voi-spec", "voi-data"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--min-samples", type=int, default=2)
    parser.add_argument("--min-observations", type=int, default=1)
    parser.add_argument("--alpha", type=float, default=1.0)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("Choose a new output directory")
    hashes = {}
    def read(name):
        path = getattr(args, name)
        if path is None:
            return None
        raw = path.read_bytes()
        hashes[name] = {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest()}
        return json.loads(raw.decode("utf-8"))
    artifacts = build_models(evaluation_cases=read("evaluation_cases"), registry=read("registry"),
        routing_rows=read("routing_data"), voi_spec=read("voi_spec"), voi_rows=read("voi_data"),
        min_samples=args.min_samples, min_observations=args.min_observations, alpha=args.alpha)
    # Validate every requested model before creating any output.
    args.output_dir.mkdir(parents=True, exist_ok=False)
    def write(name, value):
        (args.output_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    for name, artifact in artifacts.items():
        write(name + ".json", artifact)
    write("training_manifest.json", {"schema_version": 1, "inputs": hashes,
        "models": list(artifacts), "min_samples": args.min_samples,
        "min_observations": args.min_observations, "smoothing_alpha": args.alpha,
        "status": "fitted_not_clinically_validated", "llm_calls": 0})
    print("Fitted: " + ", ".join(artifacts) + "; output=" + str(args.output_dir))


if __name__ == "__main__":
    main()
