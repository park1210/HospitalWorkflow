"""Compare rule/random/adaptive routers using saved same-observation outcomes."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from app.core.agent_registry import AgentRegistry
from app.core.routing_evaluation import decisions_from_outcomes, evaluate_routing
from app.core.routing_utility import nonnegative


def compare(outcomes, registry, seeds=(0, 1, 2)):
    if not outcomes or not seeds or any(type(s) is not int for s in seeds):
        raise ValueError("Nonempty outcomes and integer seeds required")
    agents = {a["agent_id"]: a for a in registry.snapshot()["agents"] if a["role"] == "specialty"}
    # Validate even rows where adaptive abstains; unavailable data must not look like success.
    grouped, patient_splits = {}, {}
    for r in outcomes:
        a = agents.get(r["agent_id"])
        if a is None or any(r.get(k) != a[k] for k in ("model", "version")):
            raise ValueError("Missing or mismatched model/version")
        if type(r.get("correct")) is not bool or not nonnegative(r.get("latency_seconds")) or (r.get("cost") is not None and not nonnegative(r["cost"])):
            raise ValueError("Invalid outcome measurements")
        if patient_splits.setdefault(r["patient_id"], r["split"]) != r["split"]:
            raise ValueError("Patient crosses evaluation splits")
        grouped.setdefault((r["patient_id"], r["decision_id"]), []).append(r)
    if len(set(patient_splits.values())) != 1:
        raise ValueError("Compare validation and test in separate runs")
    decisions_from_outcomes(outcomes, registry)  # train separation, duplicate IDs, observation equality
    results = []
    for mode, seed in [("rule", 0), ("adaptive", 0), *[("random", s) for s in sorted(set(seeds))]]:
        decisions, traces = [], []
        for (patient, decision), rows in grouped.items():
            route = registry.route(rows[0]["observation"], [a["department"] for a in agents.values()], mode=mode, seed=seed)
            allowed = route["allowed_departments"]
            selected = registry.get("specialty", allowed[0])["agent_id"] if len(allowed) == 1 else None
            decision_row = dict(patient_id=patient, decision_id=decision, candidate_agent_ids=list(agents), chosen_agent_id=selected,
                                outcomes={r["agent_id"]: {k: r[k] for k in ("correct", "cost", "latency_seconds")} for r in rows if r["cost"] is not None})
            if selected is None:
                decision_row["status"] = "router_abstained"
            decisions.append(decision_row)
            traces.append(dict(patient_id=patient, decision_id=decision, route=deepcopy(route)))
        evaluation = evaluate_routing(decisions, registry.utility)
        usable = [d for d in decisions if set(d["outcomes"]) == set(agents) and d["chosen_agent_id"] is not None]
        observed = [d["outcomes"][d["chosen_agent_id"]] for d in usable]
        results.append(dict(mode=mode, seed=seed, evaluation=evaluation, traces=traces,
                            selected_accuracy=sum(o["correct"] for o in observed) / len(observed) if observed and len(observed) == len(decisions) else None,
                            observed_subset_accuracy=sum(o["correct"] for o in observed) / len(observed) if observed else None))
    return dict(new_model_calls=0, weights=registry.utility.artifact["weights"], utility_sha256=registry.utility.fingerprint,
                split=next(iter(patient_splits.values())), decisions=len(grouped), results=results,
                interpretation="Replay, not fresh LLM evaluation. Oracle is hindsight max utility within complete candidate outcomes. Abstentions/missing costs retain incomplete coverage. Random seeds are repetitions, not new patients.")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("outcomes", "registry", "utility"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2])
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    read = lambda path: json.loads(path.read_text(encoding="utf-8"))
    result = compare(read(args.outcomes), AgentRegistry(read(args.registry), read(args.utility)), args.seeds)
    result["input_sha256"] = {k: hashlib.sha256(getattr(args, k).read_bytes()).hexdigest() for k in ("outcomes", "registry", "utility")}
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    lines = ["# Routing baseline comparison", "", result["interpretation"], "", "| Router | Seed | Coverage | Mean regret | Selected accuracy |", "|---|---:|---:|---:|---:|"]
    for r in result["results"]:
        lines.append(f"| {r['mode']} | {r['seed']} | {r['evaluation']['coverage']} | {r['evaluation']['mean_regret']} | {r['selected_accuracy']} |")
    (args.output_dir / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Routing replay complete; no model calls: {args.output_dir}")


if __name__ == "__main__":
    main()
