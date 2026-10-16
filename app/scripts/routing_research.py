"""Fit contextual routing utility or evaluate held-out counterfactual regret."""
import argparse
import json
from pathlib import Path
from app.core.agent_registry import AgentRegistry
from app.core.routing_utility import fit_utility, RoutingUtility
from app.core.routing_evaluation import evaluate_routing, decisions_from_outcomes


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["fit", "evaluate"])
    p.add_argument("--registry", type=Path, required=True)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--utility", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--min-samples", type=int, default=2)
    p.add_argument("--accuracy-weight", type=float, default=1)
    p.add_argument("--cost-weight", type=float, default=0)
    p.add_argument("--latency-weight", type=float, default=0)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError("Choose a new output file")
    def read(path):
        return json.loads(path.read_text(encoding="utf-8"))
    registry, rows = AgentRegistry(read(args.registry)), read(args.data)
    if args.action == "fit":
        result = fit_utility(rows, registry, min_samples=args.min_samples, weights={
            "accuracy": args.accuracy_weight, "cost": args.cost_weight, "latency": args.latency_weight})
    else:
        if not args.utility:
            p.error("evaluate requires --utility")
        registry = AgentRegistry(read(args.registry), read(args.utility))
        if rows and "candidate_agent_ids" not in rows[0]:
            rows = decisions_from_outcomes(rows, registry)
        result = evaluate_routing(rows, registry.utility)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
