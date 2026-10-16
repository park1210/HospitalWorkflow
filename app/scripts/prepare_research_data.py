"""Generate a labelled synthetic bundle or validate an externally reviewed bundle."""
import argparse
import json
from pathlib import Path
from app.core.research_dataset import synthetic_bundle, validate_bundle
from app.core.embedding_builder import build_embeddings


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bundle", type=Path, help="Validate this existing bundle instead of generating synthetic data")
    p.add_argument("--output-dir", type=Path)
    args = p.parse_args()
    if args.bundle:
        print(json.dumps(validate_bundle(json.loads(args.bundle.read_text(encoding="utf-8"))), ensure_ascii=False))
        return
    if not args.output_dir or args.output_dir.exists():
        p.error("Generation requires a new --output-dir")
    root = Path(__file__).resolve().parents[1]
    bundle = synthetic_bundle(json.loads((root / "data/longitudinal_synthetic.example.json").read_text(encoding="utf-8")))
    artifacts = {"bundle": bundle, "memory": bundle["memory"], "annotations": bundle["annotations"],
                 "expected_diagnoses": bundle["expected_diagnoses"], "cases": bundle["cases"]}
    for split, patients in bundle["splits"].items():
        artifacts[f"cases_{split}"] = [c for c in bundle["cases"] if c["longitudinal"]["patient_id"] in patients]
        artifacts[f"routing_probes_{split}"] = [
            {"patient_id": c["longitudinal"]["patient_id"], "decision_id": c["case_id"], "split": split,
             "observation": {"chief_complaint": c["doctor_visible_info"]["chief_complaint"]},
             "expected_diagnoses": ["unresolved"]} for c in artifacts[f"cases_{split}"]]
    artifacts["embeddings_lexical"] = build_embeddings(bundle["memory"]["records"], bundle["cases"])
    args.output_dir.mkdir(parents=True)
    for name, payload in artifacts.items():
        (args.output_dir / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(validate_bundle(bundle), ensure_ascii=False))


if __name__ == "__main__":
    main()
