"""Generate a reproducible, explicitly unreviewed longitudinal stress benchmark."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from app.core.longitudinal_memory import PatientMemoryStore, visit_identity, timestamp
from app.core.memory_evaluation import evaluate_memory, visit_key
from app.scripts.run_paper_experiments import prepare

ROOT = Path(__file__).resolve().parents[2]
GROUPS = ("distractors", "superseded", "conflict", "paraphrase")


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def build(output):
    output.mkdir(parents=True, exist_ok=False)
    read = lambda name: json.loads((ROOT / "app/data/voi_synthetic" / (name + ".json")).read_text(encoding="utf-8"))
    templates = read("cases")
    records, partitions, all_annotations, scenario_rows = [], {}, {}, []
    for split_no, split in enumerate(("train", "validation", "test")):
        cases, labels, annotations = [], {}, {}
        for group_no, group in enumerate(GROUPS):
            patient = f"challenge-{split}-{group}"
            prior_letter = "AB"[(group_no + split_no) % 2]

            def record(suffix, text, date="2026-01-01T00:00:00Z", visit="v0", supersedes=None):
                memory_id = patient + "-" + suffix
                records.append(dict(memory_id=memory_id, patient_id=patient, visit_id=visit, visit_started_at=date,
                                    observed_at=date, available_at=date, source_id="synthetic-challenge-v1",
                                    kind="history", text=text, supersedes=supersedes or []))
                return memory_id

            prior = record("indicator", f"Prior synthetic indicator {prior_letter}.")
            for j, text in enumerate(("Remote ankle injury resolved.", "Dental cleaning completed.", "Travel paperwork reviewed.")):
                record(f"noise-{j}", text)
            extra_relevant = []
            if group == "conflict":
                extra_relevant = [record("positive", "Patient reports discomfort."), record("negative", "Patient denies discomfort.")]
            updated = None
            if group == "superseded":
                updated = record("update", f"Prior synthetic indicator {'B' if prior_letter == 'A' else 'A'}.",
                                 "2026-02-02T00:00:00Z", "v1", [prior])
            record("future", "Future sentinel must never be visible.", "2027-01-01T00:00:00Z", "v3")
            for visit_no in (1, 2):
                # Current truth is balanced; historical indicators can disagree with it.
                truth = (group_no + visit_no + split_no) % 2
                case = deepcopy(templates[truth])
                case["case_id"] = f"{patient}-v{visit_no}"
                case["longitudinal"] = dict(patient_id=patient, visit_id=f"v{visit_no}",
                                             started_at=f"2026-0{visit_no + 1}-01T00:00:00Z")
                case["doctor_visible_info"]["chief_complaint"] = (
                    "Recurring marker concern" if group == "paraphrase" else "Prior synthetic indicator discomfort")
                case["patient_visible_info"]["history"] = (
                    "Synthetic indicator is present." if truth == 0 else "Synthetic indicator is absent.")
                cases.append(case)
                key = visit_key(case["longitudinal"])
                labels[key] = "Synthetic " + "AB"[truth]
                active = updated if updated and visit_no == 2 else prior
                annotations[key] = dict(relevant_memory_ids=[active, *extra_relevant],
                                        stale_memory_ids=[prior] if updated and visit_no == 2 else [])
                scenario_rows.append(dict(patient_id=patient, visit_id=f"v{visit_no}", split=split, group=group))
        save(output / f"cases_{split}.json", cases)
        save(output / f"labels_{split}.json", labels)
        save(output / f"annotations_{split}.json", annotations)
        partitions[split] = cases
        all_annotations.update(annotations)
    store = PatientMemoryStore(records)
    save(output / "memory.json", store.snapshot())
    save(output / "scenarios.json", scenario_rows)
    model = read("model")
    save(output / "model.json", model)
    expensive = deepcopy(model)
    expensive["revision"] += ":challenge-cost-sensitivity"
    for action in expensive["actions"]:
        if action["type"] == "request_test":
            action["cost"]["money"] = .4
        elif action["type"] in {"ask_patient", "consult_specialty"}:
            action["cost"]["money"] = 1.
    save(output / "model_costly.json", expensive)
    for source, dest in (("registry_local", "registry"), ("routing_utility_bounded", "routing_utility"), ("prices_local_api_only", "prices")):
        data = json.loads((ROOT / "app/data/research_synthetic_v1" / (source + ".json")).read_text(encoding="utf-8"))
        save(output / (dest + ".json"), data)
    for split in ("validation", "test"):
        for costly in (False, True):
            plan = dict(schema_version=1, provenance=dict(synthetic=True, review_status="unreviewed",
                        scope="designed challenge cases; not clinical evidence", split=split,
                        routing="pre-existing toy-probe utility, not trained on challenge cases"),
                        repeats=1, retrieved_mode="selective", top_k=1, minute_limit=30,
                        inputs=dict(cases=f"cases_{split}.json", labels=f"labels_{split}.json", memory="memory.json",
                                    annotations=f"annotations_{split}.json", registry="registry.json", routing_utility="routing_utility.json",
                                    prices="prices.json", scenarios="scenarios.json", voi_model="model_costly.json" if costly else "model.json"))
            path = output / f"plan_{split}{'_costly' if costly else ''}.json"
            save(path, plan)
            prepare(path.resolve())
    audit = audit_memory(partitions, all_annotations, store, scenario_rows)
    save(output / "memory_audit.json", audit)
    save(output / "provenance.json", dict(schema_version=1, synthetic=True, review_status="unreviewed",
        generator="app.scripts.prepare_challenge_benchmark:v1", patients=12, visits=24,
        split_patients={s: sorted({c["longitudinal"]["patient_id"] for c in cs}) for s, cs in partitions.items()},
        limitations=["Fixed curated synthetic history, not prior LLM-generated visits", "Only two categorical diagnoses",
                     "Lexical cues and labels are designed, not clinically adjudicated", "Routing utility remains the earlier toy probe model",
                     "No semantic embeddings supplied; paraphrase stress exposes lexical limitations", "No clinical misuse labels"] ))
    lines = ["# Longitudinal challenge benchmark", "", "12 patients / 24 visits; 4 patients per split. Synthetic, unreviewed.",
             "", "| Test group | Mode | k | Precision (macro) | Recall (macro) | Stale selected |", "|---|---|---:|---:|---:|---:|"]
    for row in audit["summary"]:
        if row["split"] == "test":
            lines.append(f"| {row['group']} | {row['mode']} | {row['top_k']} | {row['precision']} | {row['recall']} | {row['stale_selected']} |")
    lines += ["", "No model calls in memory audit. NA is represented by None. This measures retrieval, not diagnosis or clinical benefit.",
              "Run plan_test.json for B0-B4; plan_test_costly.json changes test/interview/consult costs to exercise memory acquisition.",
              "Do not tune on test. Use validation plan for pipeline debugging. See docs/challenge_benchmark.md."]
    (output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return audit


def audit_memory(partitions, annotations, store, scenarios):
    patient_sets = [{c["longitudinal"]["patient_id"] for c in cs} for cs in partitions.values()]
    if any(a & b for i, a in enumerate(patient_sets) for b in patient_sets[i + 1:]):
        raise ValueError("Patient split leakage")
    groups = {(r["patient_id"], r["visit_id"]): r["group"] for r in scenarios}
    rows = []
    for split, cases in partitions.items():
        for case in cases:
            identity = visit_identity(case)
            key = visit_key(identity)
            query = case["doctor_visible_info"]["chief_complaint"]
            eligible = store.retrieve(identity, query, "full_history")["records"]
            for mode, k in (("none", 1), ("full_history", 1), ("selective", 1), ("selective", 3)):
                context = store.retrieve(identity, query, mode, k)
                for r in context["records"]:
                    if (r["patient_id"] != identity["patient_id"] or r["visit_id"] == identity["visit_id"]
                            or timestamp(r["available_at"]) > timestamp(identity["started_at"])):
                        raise ValueError("Memory boundary violation")
                metrics = evaluate_memory(context, [], annotations[key], [r["memory_id"] for r in eligible])
                rows.append(dict(split=split, group=groups[(identity["patient_id"], identity["visit_id"])],
                                 identity=identity, mode=mode, top_k=k, metrics=metrics,
                                 conflict_candidates=len(context.get("conflicts", []))))
    summary = []
    for split in partitions:
        for group in GROUPS:
            for mode, k in (("none", 1), ("full_history", 1), ("selective", 1), ("selective", 3)):
                subset = [r for r in rows if (r["split"], r["group"], r["mode"], r["top_k"]) == (split, group, mode, k)]
                item = dict(split=split, group=group, mode=mode, top_k=k, visits=len(subset))
                for metric in ("precision", "recall"):
                    values = [r["metrics"][metric]["value"] for r in subset if r["metrics"][metric]["value"] is not None]
                    item[metric] = sum(values) / len(values) if values else None
                    item[metric + "_coverage"] = len(values) / len(subset)
                item["stale_selected"] = sum(r["metrics"]["stale_retrieval_rate"]["numerator"] or 0 for r in subset)
                summary.append(item)
    return dict(status="passed", boundary_checks=len(rows), new_llm_calls=0, rows=rows, summary=summary)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", type=Path, required=True, help="New directory only")
    args = p.parse_args()
    audit = build(args.output_dir)
    print(f"Created 12 patients / 24 visits; {audit['boundary_checks']} retrieval checks passed: {args.output_dir}")


if __name__ == "__main__":
    main()
