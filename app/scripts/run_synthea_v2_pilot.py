"""Existing simulator's v2 Memory/Router pilot. Offline is the default; no VoI evaluation."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from app.core.agent_registry import AgentRegistry
from app.core.clinical_observation import memory_query
from app.core.longitudinal_memory import timestamp
from app.core.longitudinal_runner import run_longitudinal
from app.data.synthea_v2_adapter import convert_case


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def recommended_ids(path):
    """Read ranked case IDs only; report prose never becomes an agent input."""
    groups = {"routing": [], "memory": []}
    section = None
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("## "):
            section = line[3:].strip().lower()
        elif section in groups and line.startswith("|"):
            cells = [c.strip() for c in line.strip("| ").split("|")]
            if cells[0].isdigit():
                if int(cells[0]) != len(groups[section]) + 1 or not cells[1].startswith("symptom-v1-"):
                    raise ValueError("Invalid recommendation rank or case ID")
                groups[section].append(cells[1])
    for section, count in (("routing", 10), ("memory", 9)):
        if len(groups[section]) != count or len(set(groups[section])) != count:
            raise ValueError(f"Expected {count} unique {section} recommendations")
    return groups


class PilotBoundary:
    def __init__(self, registry, *, live=False, context_chars=24000, max_calls=8):
        self.registry, self.live = registry, live
        self.context_chars, self.max_calls = context_chars, max_calls
        self.traces, self.calls = [], 0

    def chat_json(self, system, prompt, model=None, schema=None):
        payload = json.loads(prompt)
        observed = payload["observation"]
        forbidden = {"evaluation", "primary_specialty", "gold_condition_description", "module", "cause",
                     "source_event_store", "current_symptom_provenance", "current_symptom_annotation"}
        def check(obj):
            if isinstance(obj, dict):
                assert not (set(obj) & forbidden), "Hidden fields in model payload"
                for value in obj.values(): check(value)
            elif isinstance(obj, list):
                for value in obj: check(value)
        check(payload)
        # Includes system, serialized payload and output schema; token count is an estimate only.
        chars = len(system) + len(prompt) + len(json.dumps(schema, ensure_ascii=False))
        trace = {"observation": observed, "routing_context": payload.get("routing_context"),
                 "role": payload["role"], "model_binding": model, "memory_query": memory_query(observed),
                 "input_characters": chars, "estimated_input_tokens": math.ceil(chars / 4),
                 "token_estimate_method": "ceil(characters/4); not a tokenizer/context guarantee",
                 "context_limit_characters": self.context_chars,
                 "candidate_actions": payload.get("candidate_actions"), "leakage_keys_check": True,
                 "requested_selector": "specialist_heuristic", "executed_selector": None}
        self.traces.append(trace)
        if chars > self.context_chars:
            trace["status"] = "context_limit_exceeded"
            raise RuntimeError("Context character budget exceeded; no truncation or selective fallback")
        if not self.live:
            trace["status"] = "stopped_before_model_call"
            raise RuntimeError("Intentional offline boundary")
        if self.calls >= self.max_calls:
            trace["status"] = "model_call_limit_exceeded"
            raise RuntimeError("Pilot call limit")
        from app.llm.ollama_client import OllamaClient
        self.calls += 1
        trace["status"] = "live_model_requested"
        return OllamaClient().chat_json(system, prompt, model=model, schema=schema)


def run_case(case, mode, manifest, args):
    registry = AgentRegistry(manifest)
    boundary = PilotBoundary(registry, live=args.live, context_chars=args.context_chars)
    report = run_longitudinal([case], mode={"no_memory": "none", "full_history_budgeted": "full_history",
                                          "selective": "selective"}[mode], top_k=args.top_k,
        memory_source="fixed", registry_manifest=manifest, routing_mode="adaptive", client=boundary,
        action_selector="specialist_heuristic", minute_limit=120)
    visit = report["visits"][0]
    memory = visit["memory_context"]
    cutoff = timestamp(case["index_encounter_start"])
    assert all(r["patient_id"] == case["longitudinal"]["patient_id"]
               and r["visit_id"] != case["index_encounter_id"]
               and timestamp(r["available_at"]) < cutoff for r in memory["records"])
    first = boundary.traces[0] if boundary.traces else None
    # Recompute the unchanged public-input router for a full, stable score trace.
    routing = registry.select_specialty(first["observation"], first["observation"].get("longitudinal_memory", {}),
        [a["department"] for a in manifest["agents"] if a["role"] == "specialty"]) if first else None
    binding = registry.get("specialty", routing["selected_specialty"]) if routing else None
    if first:
        assert first["role"] == "specialty" and first["model_binding"] == binding["model"]
    status = (boundary.traces[-1]["status"] if boundary.traces and
              boundary.traces[-1]["status"] != "live_model_requested" else report["status"])
    runtime = next(iter(visit["final_state"]["cases"].values()))
    return {"case_id": case["case_id"], "memory_mode": mode, "status": status,
            "runner_status": report["status"], "boundary_reached": bool(first),
            "expected_offline_exception": status == "stopped_before_model_call",
            "actual_llm_calls": boundary.calls, "routing": routing, "binding": binding,
            "memory": memory, "boundary_traces": boundary.traces,
            "requested_selector": "specialist_heuristic",
            "executed_selector": runtime.get("voi_state", {}).get("selector_status", {}).get("executed_selector"),
            "failure_detail": visit.get("failure_detail"),
            "live_final_state": visit["final_state"] if args.live else None}


def evaluate(results, sources):
    for result in results:
        gold = sources[result["case_id"]]["evaluation"]
        selected = (result["routing"] or {}).get("selected_specialty")
        valid = selected is not None and result["status"] != "context_limit_exceeded"
        result["evaluation"] = {"gold_specialty": gold["primary_specialty"],
            "acceptable_specialties": gold["acceptable_specialties"],
            "gold_in_registry": gold["primary_specialty"] in (result["routing"] or {}).get("candidate_departments", []),
            "strict_correct": selected == gold["primary_specialty"] if valid else None,
            "acceptable_correct": selected in gold["acceptable_specialties"] if valid else None}
    summaries = {}
    for mode in sorted({r["memory_mode"] for r in results}):
        rows = [r for r in results if r["memory_mode"] == mode]
        valid = [r for r in rows if r["evaluation"]["strict_correct"] is not None]
        summaries[mode] = {"runs": len(rows), "evaluated_routing_runs": len(valid),
            "statuses": dict(Counter(r["status"] for r in rows)),
            "strict_accuracy": sum(r["evaluation"]["strict_correct"] for r in valid)/len(valid) if valid else None,
            "acceptable_accuracy": sum(r["evaluation"]["acceptable_correct"] for r in valid)/len(valid) if valid else None}
    return {"summary": summaries, "results": results, "memory_accuracy_metrics": "not_computed_no_relevance_gold"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("current_symptom_presentation_benchmark_v2.jsonl"))
    parser.add_argument("--registry", type=Path, default=Path("app/data/challenge_v4/registry.json"))
    parser.add_argument("--routing-case-ids", type=Path, help="JSON list of 10 recommended case IDs")
    parser.add_argument("--candidate-report", type=Path,
                        default=Path("final_task_candidate_report_v2.md"),
                        help="Ranked Routing/Memory recommendations; used when present")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/synthea_v2"))
    parser.add_argument("--context-chars", type=int, default=24000)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--live", action="store_true", help="Actual specialty calls; default stops before calls")
    args = parser.parse_args()
    if args.context_chars < 1 or args.top_k < 1: parser.error("Budgets must be positive")
    if args.output_dir.exists(): parser.error("Choose a new output directory; existing results are preserved")
    fingerprint = digest(args.source)
    sources = [json.loads(l) for l in args.source.read_text(encoding="utf-8-sig").splitlines() if l.strip()]
    by_id = {r["case_id"]: r for r in sources}
    assert len(by_id) == len(sources)
    manifest = json.loads(args.registry.read_text(encoding="utf-8-sig"))
    AgentRegistry(manifest)
    routing = [r for r in sources if r["final_task_eligibility"]["routing_final_candidate"]]
    recommendations = recommended_ids(args.candidate_report) if args.candidate_report.is_file() else None
    if recommendations:
        for task, ids in recommendations.items():
            if any(i not in by_id or not by_id[i]["final_task_eligibility"][task + "_final_candidate"] for i in ids):
                raise ValueError(f"Ineligible or missing {task} recommendation")
    if args.routing_case_ids:
        ids = json.loads(args.routing_case_ids.read_text(encoding="utf-8-sig"))
        assert len(ids) == len(set(ids)) == 10
        assert all(i in {r["case_id"] for r in routing} for i in ids)
        routing = [by_id[i] for i in ids]
        selection = "provided_recommendation_ids"
    elif recommendations:
        routing = [by_id[i] for i in recommendations["routing"]]
        selection = "ranked_candidate_report"
    else:
        chosen = [next(r for r in routing if r["evaluation"]["primary_specialty"] == d)
                  for d in ("otolaryngology", "surgery", "gastroenterology")]
        routing = (chosen + [r for r in routing if r not in chosen])[:10]
        selection = "provisional_one_per_specialty_then_source_order; recommendation_list_not_found"
    memory = [r for r in sources if r["final_task_eligibility"]["memory_final_candidate"]]
    if recommendations:
        memory = [by_id[i] for i in recommendations["memory"]]
    converted, patient_traces = {}, []
    for source in sources:
        case, trace = convert_case(source)
        converted[source["case_id"]] = case
        patient_traces.append({"case_id": source["case_id"], "patient_input": case["synthea_v2_patient_input"], **trace})
    args.output_dir.mkdir(parents=True)
    def save(name, value):
        (args.output_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    cache = {}
    def batch(rows, modes):
        results = []
        for source in rows:
            for mode in modes:
                key = (source["case_id"], mode)
                if key not in cache:
                    cache[key] = run_case(converted[key[0]], mode, manifest, args)
                    print(key[0], mode, cache[key]["status"], flush=True)
                results.append(deepcopy(cache[key]))
        return evaluate(results, by_id)
    r_modes, m_modes = ("no_memory", "selective"), ("no_memory", "full_history_budgeted", "selective")
    r_smoke, m_smoke = batch(routing[:3], r_modes), batch(memory[:3], m_modes)
    save("routing_smoke.json", r_smoke)
    save("memory_smoke.json", m_smoke)
    smoke_ok = all(r["boundary_reached"] and (args.live or r["status"] in
        {"stopped_before_model_call", "context_limit_exceeded"}) for r in r_smoke["results"] + m_smoke["results"])
    if smoke_ok:
        save("routing_pilot_results.json", batch(routing, r_modes))
        save("memory_pilot_results.json", batch(memory, m_modes))
    (args.output_dir / "patient_agent_trace.jsonl").write_text(
        "\n".join(json.dumps(t, ensure_ascii=False) for t in patient_traces) + "\n", encoding="utf-8")
    assert digest(args.source) == fingerprint
    save("validation.json", {"source": str(args.source), "source_sha256": fingerprint, "source_unchanged": True,
        "registry": str(args.registry), "registry_sha256": digest(args.registry), "registry_snapshot": manifest,
        "source_cases": len(sources), "routing_eligible": sum(r["final_task_eligibility"]["routing_final_candidate"] for r in sources),
        "routing_pilot_selection": selection, "routing_ids": [r["case_id"] for r in routing],
        "candidate_report": str(args.candidate_report) if recommendations else None,
        "candidate_report_sha256": digest(args.candidate_report) if recommendations else None,
        "memory_pilot_selection": "ranked_candidate_report" if recommendations else "source_eligibility_order",
        "memory_ids": [r["case_id"] for r in memory], "patient_grounded_cases": len(patient_traces),
        "voi_final_candidates": sum(r["final_task_eligibility"]["voi_final_candidate"] for r in sources),
        "outcome_models": sum(r["final_task_eligibility"].get("outcome_model") is not None for r in sources),
        "technical_smoke_passed": smoke_ok, "unique_case_mode_executions": len(cache),
        "actual_llm_calls": sum(r["actual_llm_calls"] for r in cache.values()),
        "context_chars": args.context_chars, "top_k": args.top_k,
        "limitations": ["Registry coverage is not expanded using gold labels", "Offline is not clinical/model accuracy",
                        "Context overflow is an expected non-execution status, not a successful full-history model run",
                        "Date-only memory uses next-day availability upper bound", "No official memory retrieval accuracy"]})


if __name__ == "__main__":
    main()
