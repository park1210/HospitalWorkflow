"""Compare lexical and saved-vector retrieval; never call an embedding server."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from app.core.longitudinal_memory import PatientMemoryStore, visit_identity, timestamp
from app.core.memory_evaluation import evaluate_memory, visit_key, validate_annotations
from app.core.memory_retrieval import MemoryEmbeddings


def compare(cases, memory, annotations, *, embeddings=None, top_ks=(1, 3), groups=None):
    if not cases or not top_ks or any(type(k) is not int or k < 1 for k in top_ks):
        raise ValueError("Need nonempty cases and positive top-k values")
    identities = [visit_identity(c) for c in cases]
    keys = [visit_key(i) for i in identities]
    validate_annotations(annotations)
    if len(keys) != len(set(keys)) or set(keys) != set(annotations):
        raise ValueError("Unique visits and exact annotation coverage required")
    if memory.get("schema_version") != 1:
        raise ValueError("Unsupported memory schema")
    store = PatientMemoryStore(memory["records"])
    vectors = MemoryEmbeddings(embeddings) if embeddings is not None else None
    vector_name = ("lexical_hash_vectors" if vectors and vectors.payload["model_id"] == "lexical-hash-256" else "saved_model_vectors")
    rows = []
    settings = [("none", "none", 1), ("full_history", "full_history", 1)]
    settings += [("lexical", "selective", k) for k in sorted(set(top_ks))]
    if vectors:
        settings += [(vector_name, "semantic", k) for k in sorted(set(top_ks))]
    for case, identity, key in zip(cases, identities, keys):
        query = case.get("doctor_visible_info", {}).get("chief_complaint", "")
        eligible = store.retrieve(identity, query, "full_history")["records"]
        for method, mode, k in settings:
            context = store.retrieve(identity, query, mode, k, embeddings=vectors)
            for r in context["records"]:
                if (r["patient_id"] != identity["patient_id"] or r["visit_id"] == identity["visit_id"]
                        or timestamp(r["visit_started_at"]) >= timestamp(identity["started_at"])
                        or timestamp(r["available_at"]) > timestamp(identity["started_at"])):
                    raise ValueError("Retrieval crossed patient/visit/time boundary")
            metrics = evaluate_memory(context, [], annotations[key], [r["memory_id"] for r in eligible])
            rows.append(dict(visit=key, group=(groups or {}).get(key, "unspecified"), method=method, top_k=k,
                             precision=metrics["precision"]["value"], recall=metrics["recall"]["value"],
                             stale_rate=metrics["stale_retrieval_rate"]["value"], retrieved_ids=metrics["retrieved_ids"],
                             conflict_candidates=len(context.get("conflicts", []))))
    summary = []
    for group in ["ALL", *sorted({r["group"] for r in rows})]:
        for method, _, k in settings:
            subset = [r for r in rows if r["method"] == method and r["top_k"] == k and (group == "ALL" or r["group"] == group)]
            result = dict(group=group, method=method, top_k=k, visits=len(subset))
            for metric in ("precision", "recall", "stale_rate"):
                values = [r[metric] for r in subset if r[metric] is not None]
                result[metric] = sum(values) / len(values) if values else None
                result[metric + "_coverage"] = len(values) / len(subset)
            summary.append(result)
    return dict(new_model_calls=0, summary=summary, rows=rows,
                embedding_model=vectors.payload["model_id"] if vectors else None,
                embedding_revision=vectors.payload["revision"] if vectors else None,
                embedding_sha256=vectors.fingerprint if vectors else None,
                interpretation="Saved vectors are supplied artifacts, not verified clinical semantics. Macro retrieval metrics; not diagnosis or misuse accuracy.")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("cases", "memory", "annotations"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--embeddings", type=Path)
    p.add_argument("--scenarios", type=Path)
    p.add_argument("--top-k", type=int, nargs="+", default=[1, 3])
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--paper-plan", type=Path, help="Also create a semantic B0-B4 plan with the same data/settings")
    args = p.parse_args()
    read = lambda path: json.loads(path.read_text(encoding="utf-8"))
    scenarios = read(args.scenarios) if args.scenarios else []
    groups = {visit_key(r): r["group"] for r in scenarios}
    if len(groups) != len(scenarios):
        raise ValueError("Duplicate scenario IDs")
    result = compare(read(args.cases), read(args.memory), read(args.annotations), embeddings=read(args.embeddings) if args.embeddings else None,
                     top_ks=args.top_k, groups=groups)
    semantic_plan = None
    if args.paper_plan:
        if not args.embeddings or result["embedding_model"] == "lexical-hash-256":
            raise ValueError("Semantic experiment plan requires non-lexical model vectors")
        from app.scripts.run_paper_experiments import prepare
        semantic_plan, _, _ = prepare(args.paper_plan.resolve())
        for name in ("cases", "memory", "annotations"):
            original = (args.paper_plan.resolve().parent / semantic_plan["inputs"][name]).read_bytes()
            if hashlib.sha256(original).digest() != hashlib.sha256(getattr(args, name).read_bytes()).digest():
                raise ValueError("Comparison data differs from paper plan: " + name)
        semantic_plan["inputs"] = {k: str((args.paper_plan.resolve().parent / v).resolve()) for k, v in semantic_plan["inputs"].items()}
        semantic_plan["inputs"]["embeddings"] = str(args.embeddings.resolve())
        semantic_plan["retrieved_mode"] = "semantic"
    result["input_sha256"] = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name in
                              ("cases", "memory", "annotations", "embeddings", "scenarios") if (path := getattr(args, name)) is not None}
    args.output_dir.mkdir(parents=True, exist_ok=False)
    if semantic_plan is not None:
        target = args.output_dir / "plan_semantic.json"
        target.write_text(json.dumps(semantic_plan, ensure_ascii=False, indent=2), encoding="utf-8")
        prepare(target.resolve())
    (args.output_dir / "comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    with (args.output_dir / "summary.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(result["summary"][0]))
        writer.writeheader()
        writer.writerows(result["summary"])
    lines = ["# Memory retrieval comparison", "", result["interpretation"], "", f"Embedding model: {result['embedding_model']}; new model calls: 0", "",
             "| Group | Method | k | Precision | Recall | Stale rate |", "|---|---|---:|---:|---:|---:|"]
    for r in result["summary"]:
        lines.append(f"| {r['group']} | {r['method']} | {r['top_k']} | {r['precision']} | {r['recall']} | {r['stale_rate']} |")
    (args.output_dir / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Retrieval comparison complete; no model calls: {args.output_dir}")


if __name__ == "__main__":
    main()
