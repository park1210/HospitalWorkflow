"""Run patient-linked visits with the real LLM policy and selected memory mode."""
import argparse
import json
from pathlib import Path

from app.core.longitudinal_runner import run_with_recovery


def print_trace(report):
    """Concise trace from persisted audit/state, including real backend/model names."""
    for visit in report["visits"]:
        runtime = next(iter(visit["final_state"]["cases"].values()))
        print("[VISIT]", visit["identity"]["patient_id"], visit["identity"]["visit_id"])
        for call in runtime["llm_audit"]:
            memory = call.get("memory_context", visit["memory_context"])
            print("  Memory:", [r["memory_id"] for r in memory.get("records", [])])
            print("  Routing:", call.get("routing", {}).get("selected_specialty"),
                  "Model:", call["model"], "Backend:", call["backend"], "Status:", call["status"])
            print("  Candidates:", json.dumps(call.get("candidate_actions", []), ensure_ascii=False))
            print("  Selected:", json.dumps(call.get("decision", {}), ensure_ascii=False))
        print("  Evidence/state:", json.dumps({
            "questions": runtime["question_history"], "tests": runtime["test_results"],
            "consults": runtime["consult_history"]}, ensure_ascii=False))
        print("  Final:", runtime["assessment_summary"], "Completed:", runtime["is_completed"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True, help="JSON list of cases with longitudinal identifiers")
    parser.add_argument("--output", type=Path, required=True, help="New output file; existing reports are not overwritten")
    parser.add_argument("--memory-mode", choices=["none", "full_history", "selective", "summary", "semantic"], default="none")
    parser.add_argument("--initial-memory", type=Path, help="PatientMemoryStore snapshot JSON")
    parser.add_argument("--memory-source", choices=["closed_loop", "fixed"], default="closed_loop")
    parser.add_argument("--memory-annotations", type=Path, help="Evaluation only; never sent to models")
    parser.add_argument("--max-memory-chars", type=int, help="Character budget for serialized memory records, not token count")
    parser.add_argument("--memory-embeddings", type=Path, help="Versioned offline vectors and query vectors")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--minute-limit", type=int, default=120)
    parser.add_argument("--agent-registry", type=Path)
    parser.add_argument("--routing-mode", choices=["llm", "er_only", "rule", "random", "adaptive"], default="llm")
    parser.add_argument("--routing-utility", type=Path)
    parser.add_argument("--token-prices", type=Path)
    parser.add_argument("--voi-model", type=Path, help="Explicit finite diagnosis/outcome/utility model; opt-in")
    parser.add_argument("--action-selector", choices=["bayesian_voi", "information_gain", "specialist_heuristic", "random"])
    parser.add_argument("--resume", type=Path, help="Restart uncommitted visit from a saved checkpoint/report")
    parser.add_argument("--checkpoint", type=Path, help="Defaults to OUTPUT.checkpoint.json")
    parser.add_argument("--max-retries", type=int, default=1, help="0..3 automatic failed-visit retries; default 1")
    parser.add_argument("--routing-seed", type=int, default=0)
    parser.add_argument("--trace", action="store_true", help="Print memory, routing, calls, actions and released evidence")
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Choose a new output file")
    checkpoint = args.checkpoint or args.output.with_suffix(".checkpoint.json")
    if checkpoint.resolve() == args.output.resolve():
        raise ValueError("Checkpoint and final report must differ")
    if checkpoint.exists() and (not args.resume or checkpoint.resolve() != args.resume.resolve()):
        raise ValueError("Existing checkpoint requires explicit --resume")
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("Input must be a nonempty list of visit cases")
    registry = json.loads(args.agent_registry.read_text(encoding="utf-8")) if args.agent_registry else None
    def read_optional(path):
        return json.loads(path.read_text(encoding="utf-8")) if path else None
    initial = read_optional(args.initial_memory)
    if initial is not None and initial.get("schema_version") != 1:
        raise ValueError("Unsupported memory artifact schema")
    def save_checkpoint(payload):
        import os
        import tempfile
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=checkpoint.parent, delete=False) as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            temporary = stream.name
        os.replace(temporary, checkpoint)
    result = run_with_recovery(cases, mode=args.memory_mode, top_k=args.top_k, minute_limit=args.minute_limit,
                             registry_manifest=registry, routing_mode=args.routing_mode, routing_seed=args.routing_seed,
                             initial_memory=initial["records"] if initial is not None else None, memory_source=args.memory_source,
                             memory_annotations=read_optional(args.memory_annotations), max_memory_chars=args.max_memory_chars,
                             embedding_artifact=read_optional(args.memory_embeddings),
                             routing_utility=read_optional(args.routing_utility), token_prices=read_optional(args.token_prices),
                             resume_report=read_optional(args.resume), checkpoint_callback=save_checkpoint,
                             max_retries=args.max_retries, voi_model=read_optional(args.voi_model),
                             action_selector=args.action_selector)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(f"[LONGITUDINAL] status={result['status']} visits={len(result['visits'])} output={args.output}")
    if args.trace:
        print_trace(result)
    if result["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
