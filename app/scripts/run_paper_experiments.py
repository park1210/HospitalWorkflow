"""KSC B0-B4 experiments. Default: validate and print plan, without model calls."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import time

from app.config import settings
from app.core.agent_registry import AgentRegistry
from app.core.information_outcomes import InformationOutcomes
from app.core.longitudinal_memory import PatientMemoryStore, visit_identity
from app.core.memory_evaluation import visit_key, validate_annotations
from app.core.memory_retrieval import MemoryEmbeddings
from app.core.longitudinal_runner import run_with_recovery
from app.core.paper_evaluation import episode_rows, aggregate, paired
from app.scripts.run_research_demo import OfflineOnly
from app.utils.department_catalog import SUPPORTED_DEPARTMENTS

CONDITIONS = {"B0": ("none", "er_only", False), "B1": ("full_history", "er_only", False),
              "B2": ("retrieved", "er_only", False), "B3": ("retrieved", "adaptive", False),
              "B4": ("retrieved", "adaptive", True), "R0": ("retrieved", "llm", False)}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def prepare(path):
    plan = read(path)
    if plan.get("schema_version") != 1 or type(plan.get("repeats")) is not int or plan["repeats"] < 1:
        raise ValueError("Need schema_version=1 and positive repeats")
    if plan.get("retrieved_mode") not in {"selective", "semantic"}:
        raise ValueError("retrieved_mode must be selective or semantic")
    if type(plan.get("top_k")) is not int or plan["top_k"] < 1 or type(plan.get("minute_limit")) is not int or plan["minute_limit"] < 1:
        raise ValueError("Need positive top_k and minute_limit")
    required = {"cases", "labels", "memory", "registry", "routing_utility", "voi_model"}
    if not required <= set(plan["inputs"]):
        raise ValueError("Missing required input files")
    data, hashes = {}, {}
    for name, filename in plan["inputs"].items():
        source = (path.parent / filename).resolve()
        data[name] = read(source)
        hashes[name] = hashlib.sha256(source.read_bytes()).hexdigest()
    if not isinstance(data["cases"], list) or not data["cases"]:
        raise ValueError("Need nonempty cases")
    identities = [visit_identity(c) for c in data["cases"]]
    keys = {visit_key(i) for i in identities}
    scenarios = data.get("scenarios", [])
    if not isinstance(scenarios, list) or any(not isinstance(r, dict) or any(
            not isinstance(r.get(k), str) or not r[k].strip() for k in ("patient_id", "visit_id", "group")) for r in scenarios):
        raise ValueError("Scenarios require patient_id, visit_id and group strings")
    scenario_keys = [visit_key(r) for r in scenarios]
    if len(scenario_keys) != len(set(scenario_keys)) or (scenarios and not keys <= set(scenario_keys)):
        raise ValueError("Scenario rows must be unique and cover all planned visits")
    if len(keys) != len(identities) or set(data["labels"]) != keys:
        raise ValueError("Need unique visits and exactly one diagnosis label per planned visit")
    model = InformationOutcomes(data["voi_model"])
    for label in data["labels"].values():
        accepted = label if isinstance(label, list) else [label]
        if not accepted or any(not isinstance(x, str) or not x.strip() for x in accepted):
            raise ValueError("Diagnosis labels must be nonempty strings or accepted alias lists")
        if not any(x in model.artifact["diagnoses"] for x in accepted):
            raise ValueError("Each label must include a canonical VoI diagnosis")
    registry = AgentRegistry(data["registry"], data["routing_utility"])
    training = registry.utility.training_patients | set(model.artifact["provenance"].get("training_patients", []))
    if training & {i["patient_id"] for i in identities}:
        raise ValueError("Evaluation patients overlap fitted model training")
    annotations = data.get("annotations", {})
    departments = data.get("gold_departments", {})
    if not isinstance(departments, dict) or set(departments) - keys or any(
            not isinstance(v, list) or not v or any(d not in SUPPORTED_DEPARTMENTS for d in v) for v in departments.values()):
        raise ValueError("Gold departments must map known visit keys to nonempty canonical department lists")
    validate_annotations(annotations)
    if set(annotations) - keys or any("misused_memory_ids" in a for a in annotations.values()):
        raise ValueError("Common annotations must be in-scope and cannot contain run-specific misuse labels")
    if data["memory"].get("schema_version") != 1:
        raise ValueError("Unsupported memory schema")
    store = PatientMemoryStore(data["memory"]["records"])
    embeddings = MemoryEmbeddings(data["embeddings"]) if data.get("embeddings") else None
    if plan["retrieved_mode"] == "semantic" and embeddings is None:
        raise ValueError("Semantic retrieval requires actual embedding artifact")
    for identity, case in zip(identities, data["cases"]):
        if case.get("longitudinal", {}).get("memory_updates"):
            raise ValueError("Paired fixed-memory experiments require updates in the memory artifact")
        store.retrieve(identity, case.get("doctor_visible_info", {}).get("chief_complaint", ""),
                       plan["retrieved_mode"], plan["top_k"], embeddings=embeddings)
    return plan, data, hashes


def export(output, rows, runs, plan):
    table = aggregate(rows)
    stratified = [{"scenario_group": group, **item}
                  for group in sorted({r.get("scenario_group", "unspecified") for r in rows})
                  for item in aggregate([r for r in rows if r.get("scenario_group", "unspecified") == group])]
    comparisons = [paired(rows, a, b, metric) for a, b in (("B0", "B1"), ("B1", "B2"), ("B2", "B3"), ("B3", "B4"), ("R0", "B3"))
                   if a in {r["condition"] for r in rows} and b in {r["condition"] for r in rows}
                   for metric in ("correct_all_planned", "actions", "tests", "consults", "llm_calls", "memory_precision", "memory_recall")]
    result = {"table": table, "stratified_table": stratified, "paired": comparisons, "runs": runs, "provenance": plan.get("provenance"),
              "execution_mode": plan.get("execution_mode"),
              "status": "completed" if all(r["status"] == "completed" for r in runs) else "partial_or_failed",
              "limitations": ["B2-B3 changes consultation availability as well as routing; not a pure routing effect",
                              "Expected IG is model-derived and unavailable on non-VoI runs",
                              "Router regret requires separate same-observation counterfactual probes",
                              "Stale misuse requires condition-specific human review",
                              "Bootstrap resamples patients; small synthetic samples do not establish clinical benefit",
                              "Diagnosis scoring uses exact normalized labels/aliases, not semantic clinical adjudication"]}
    write(output / "results.json", result)
    for filename, records in (("episodes.csv", rows), ("table.csv", table), ("stratified_table.csv", stratified)):
        with (output / filename).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
    fmt = lambda x: "NA" if x is None else f"{x:.3f}"
    lines = ["# KSC B0–B4 실험 결과", "", "범위/검수: " + json.dumps(plan.get("provenance", {}), ensure_ascii=False),
             "", "실행 모드: " + str(plan.get("execution_mode")),
             "LLM 호출 수는 실패·차단된 시도도 포함합니다. offline_blocked는 실제 모델 성능 실험이 아닙니다.", "",
             "| 조건 | 계획 방문×반복 | 완료율 | 전체 계획 기준 정답률 | 완료 방문 정답률 | 평균 행동 | 평균 LLM 호출 |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for r in table:
        lines.append(f"| {r['condition']} | {r['planned_visit_runs']} | {fmt(r['completed'])} | {fmt(r['correct_all_planned'])} | {fmt(r['correct_completed'])} | {fmt(r['actions'])} | {fmt(r['llm_calls'])} |")
    lines += ["", "미실행·실패·미완료는 전체 계획 기준 정답률에서 0으로 계산합니다. 완료 방문 정답률은 별도 제공합니다.",
              "행동·토큰·시간 등 결측 지표는 0으로 채우지 않습니다. table.csv의 coverage를 반드시 함께 보고하세요.",
              "", "## 인접 조건 paired 비교 (후자 − 전자)", ""]
    for r in comparisons:
        lines.append(f"- {r['baseline']}→{r['candidate']} {r['metric']}: {fmt(r['difference'])}; CI95={r['ci95']}; patients={r['patients']}; missing={r['missing_pairs']}")
    lines += ["", "## 해석 제한", ""] + ["- " + s for s in result["limitations"]]
    (output / "paper_results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan", type=Path, default=Path("paper_experiment.example.json"))
    p.add_argument("--execute", action="store_true", help="Actually run visits, potentially making LLM calls")
    p.add_argument("--offline", action="store_true", help="Block all LLM calls; only B4 can finish on toy cases")
    p.add_argument("--conditions", nargs="+", choices=list(CONDITIONS), default=["B0", "B1", "B2", "B3", "B4"])
    p.add_argument("--repeats", type=int, help="Override repetition count for a pilot")
    p.add_argument("--output-dir", type=Path)
    args = p.parse_args()
    plan, data, hashes = prepare(args.plan.resolve())
    if args.repeats is not None:
        if args.repeats < 1:
            p.error("repeats must be positive")
        plan["repeats"] = args.repeats
    conditions = list(dict.fromkeys(args.conditions))
    print(f"Validated: {len(data['cases'])} visits x {plan['repeats']} repeats x {len(conditions)} conditions")
    for name in conditions:
        print(name, CONDITIONS[name])
    if not args.execute:
        print("No LLM calls. Add --execute --output-dir NEW_DIRECTORY to run.")
        return
    if args.output_dir is None:
        p.error("--execute requires --output-dir")
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=False)
    plan["execution_mode"] = "offline_blocked" if args.offline else "live_models_enabled"
    frozen = output / "inputs"
    frozen.mkdir()
    for name, value in data.items():
        write(frozen / (name + ".json"), value)
    model_settings = {k: getattr(settings, k) for k in ("OLLAMA_MODEL", "SPECIALTY_OLLAMA_MODEL", "TEMPERATURE", "LLM_TIMEOUT_SECONDS", "LLM_MAX_OUTPUT_TOKENS")}
    root = Path(__file__).resolve().parents[2]
    code_hashes = {str(f.relative_to(root)): hashlib.sha256(f.read_bytes()).hexdigest()
                   for folder in ("core", "llm", "agents", "scripts") for f in sorted((root / "app" / folder).glob("*.py"))}
    write(output / "manifest.json", {"plan": plan, "conditions": conditions, "offline": args.offline,
          "input_sha256": hashes, "code_sha256": code_hashes, "model_settings": model_settings,
          "repetition_note": "Repeat index is not an LLM decoding seed. Backend reproducibility is not guaranteed."})
    rows, runs = [], []
    for repeat in range(plan["repeats"]):
        # Rotate ordering to reduce systematic first-model cold-start bias.
        order = conditions[repeat % len(conditions):] + conditions[:repeat % len(conditions)]
        for name in order:
            mode, routing, voi = CONDITIONS[name]
            mode = plan["retrieved_mode"] if mode == "retrieved" else mode
            run_id = f"{name}_r{repeat + 1:02d}"
            started, report, error = time.perf_counter(), None, None
            try:
                report = run_with_recovery(data["cases"], mode=mode, top_k=plan["top_k"], minute_limit=plan["minute_limit"],
                    memory_source="fixed", initial_memory=data["memory"]["records"], memory_annotations=data.get("annotations"),
                    embedding_artifact=data.get("embeddings"), registry_manifest=data["registry"], routing_mode=routing,
                    primary_router="adaptive" if name in {"B3", "B4"} else "rule_similarity",
                    max_memory_chars=plan.get("max_memory_chars"),
                    routing_utility=data["routing_utility"], voi_model=data["voi_model"] if voi else None,
                    diagnosis_catalog=list(data["voi_model"]["diagnoses"]),
                    diagnosis_departments=dict(data["voi_model"]["diagnoses"]),
                    token_prices=data.get("prices"), max_retries=0, client=OfflineOnly() if args.offline else None,
                    checkpoint_callback=lambda value, n=run_id: write(output / (n + ".checkpoint.json"), value))
                write(output / (run_id + ".report.json"), report)
            except Exception as exc:
                error = {"type": type(exc).__name__, "message": str(exc)}
                checkpoint = output / (run_id + ".checkpoint.json")
                if checkpoint.exists():
                    report = read(checkpoint)
                write(output / (run_id + ".error.json"), error)
            status = "exception" if error else report["status"]
            runs.append({"run": run_id, "status": status, "elapsed_seconds": time.perf_counter() - started,
                         "error": error, "call_costs": report.get("call_costs") if report else None})
            new_rows = episode_rows(data["cases"], data["labels"], report, name, repeat, data.get("gold_departments"))
            scenario_groups = {(r["patient_id"], r["visit_id"]): r["group"] for r in data.get("scenarios", [])}
            for row in new_rows:
                row["scenario_group"] = scenario_groups.get((row["patient_id"], row["visit_id"]), "unspecified")
            rows.extend(new_rows)
            print(f"{run_id}: {status}", flush=True)
            result = export(output, rows, runs, plan)
    print(output / "paper_results.md")
    if result["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
