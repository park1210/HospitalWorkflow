"""Evaluate saved longitudinal reports without calling an LLM."""
import argparse
import json
from pathlib import Path

from app.core.memory_evaluation import compare_memory_benefit, evaluate_memory, validate_annotations, visit_key


def evaluate_report(report, annotations):
    validate_annotations(annotations)
    keys = {visit_key(v["identity"]) for v in report["visits"]}
    if set(annotations) - keys:
        raise ValueError("Annotations contain visits outside the report")
    results = []
    for visit in report["visits"]:
        states = list(visit["final_state"]["cases"].values())
        if len(states) != 1 or "eligible_memory_ids" not in visit:
            raise ValueError("Use a single-patient report with eligible memory IDs")
        key = visit_key(visit["identity"])
        audit = states[0].get("llm_audit", []) + [{**r, "status": "success", "role": "er"}
            for r in states[0].get("voi_state", {}).get("history", []) if "memory_citations" in r]
        results.append({"identity": visit["identity"], "metrics": evaluate_memory(
            visit["memory_context"], audit,
            annotations.get(key), visit["eligible_memory_ids"])})
    return {"mode": report["mode"], "visits": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--expected-diagnoses", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if bool(args.baseline) != bool(args.expected_diagnoses):
        parser.error("--baseline and --expected-diagnoses must be supplied together")
    if args.output.exists():
        raise ValueError("Choose a new output file")
    def read(path):
        return json.loads(path.read_text(encoding="utf-8"))
    report = read(args.report)
    result = evaluate_report(report, read(args.annotations))
    if args.baseline:
        result["comparison"] = compare_memory_benefit(read(args.baseline), report, read(args.expected_diagnoses))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(f"[MEMORY EVALUATION] visits={len(result['visits'])} output={args.output}")


if __name__ == "__main__":
    main()
