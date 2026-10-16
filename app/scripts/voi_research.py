"""Validate, fit and retrospectively evaluate explicit VoI experiments."""
import argparse
import json
from pathlib import Path
from app.core.information_outcomes import InformationOutcomes
from app.core.voi_evaluation import fit_outcomes, evaluate_voi, compare_voi


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["validate", "fit", "evaluate", "compare"])
    for name in ("model", "data", "report", "baseline", "labels", "output"):
        p.add_argument("--" + name, type=Path)
    p.add_argument("--alpha", type=float, default=1)
    args = p.parse_args()
    read = lambda path: json.loads(path.read_text(encoding="utf-8"))
    required = {"validate": ["model"], "fit": ["model", "data", "output"],
                "evaluate": ["report", "labels", "output"], "compare": ["report", "baseline", "labels", "output"]}
    if any(getattr(args, name) is None for name in required[args.action]):
        p.error("Required: " + ", ".join("--" + name for name in required[args.action]))
    if args.output and args.output.exists():
        raise ValueError("Choose a new output file")
    if args.action == "validate":
        model = InformationOutcomes(read(args.model))
        result = {"status": "valid", "model_sha256": model.fingerprint, "provenance": model.artifact["provenance"]}
    elif args.action == "fit":
        result = fit_outcomes(read(args.model), read(args.data), args.alpha)
    elif args.action == "evaluate":
        result = evaluate_voi(read(args.report), read(args.labels))
    else:
        result = compare_voi(read(args.baseline), read(args.report), read(args.labels))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
