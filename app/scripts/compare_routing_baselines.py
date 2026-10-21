
"""Compare rule/random/adaptive routers using saved outcomes.

Replay does not make fresh model calls.
Abstention is determined by decision_status, not menu size.
"""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from app.core.agent_registry import AgentRegistry
from app.core.routing_evaluation import (
    decisions_from_outcomes,
    evaluate_routing,
)
from app.core.routing_utility import nonnegative


def compare(outcomes, registry, seeds=(0, 1, 2)):
    if (
        not outcomes
        or not seeds
        or any(type(seed) is not int for seed in seeds)
    ):
        raise ValueError(
            "Nonempty outcomes and integer seeds required"
        )

    if registry.utility is None:
        raise ValueError(
            "Replay comparison requires fitted routing utility"
        )

    agents = {
        agent["agent_id"]: agent
        for agent in registry.snapshot()["agents"]
        if agent["role"] == "specialty"
    }

    grouped = {}
    patient_splits = {}

    for row in outcomes:
        agent = agents.get(row["agent_id"])

        if (
            agent is None
            or any(
                row.get(field) != agent[field]
                for field in ("model", "version")
            )
        ):
            raise ValueError(
                "Missing or mismatched model/version"
            )

        if (
            type(row.get("correct")) is not bool
            or not nonnegative(row.get("latency_seconds"))
            or (
                row.get("cost") is not None
                and not nonnegative(row["cost"])
            )
        ):
            raise ValueError(
                "Invalid outcome measurements"
            )

        patient = row["patient_id"]
        split = row["split"]

        if patient_splits.setdefault(patient, split) != split:
            raise ValueError(
                "Patient crosses evaluation splits"
            )

        key = (
            patient,
            row["decision_id"],
        )
        grouped.setdefault(key, []).append(row)

    if len(set(patient_splits.values())) != 1:
        raise ValueError(
            "Compare validation and test in separate runs"
        )

    # Check patient disjointness, duplicate outcomes,
    # model/version and identical observations.
    decisions_from_outcomes(outcomes, registry)

    results = []

    configurations = [
        ("rule", 0),
        ("adaptive", 0),
        *[
            ("random", seed)
            for seed in sorted(set(seeds))
        ],
    ]

    for mode, seed in configurations:
        decisions = []
        traces = []

        for (patient, decision), rows in grouped.items():
            observation = rows[0]["observation"]

            route = registry.route(
                observation,
                [
                    agent["department"]
                    for agent in agents.values()
                ],
                mode=mode,
                seed=seed,
            )

            decision_status = route.get(
                "decision_status"
            )
            department = route.get(
                "selected_specialty"
            )

            selected = None

            if (
                decision_status == "selected"
                and department is not None
            ):
                selected = registry.get(
                    "specialty",
                    department,
                )["agent_id"]

            decision_row = {
                "patient_id": patient,
                "decision_id": decision,
                "candidate_agent_ids": list(agents),
                "chosen_agent_id": selected,
                "outcomes": {
                    row["agent_id"]: {
                        field: row[field]
                        for field in (
                            "correct",
                            "cost",
                            "latency_seconds",
                        )
                    }
                    for row in rows
                    if row["cost"] is not None
                },
                "decision_status": (
                    "selected"
                    if selected is not None
                    else "abstained"
                ),
            }

            if selected is None:
                decision_row["status"] = "router_abstained"

            decisions.append(decision_row)

            traces.append({
                "patient_id": patient,
                "decision_id": decision,
                "route": deepcopy(route),
            })

        evaluation = evaluate_routing(
            decisions,
            registry.utility,
        )

        usable = [
            decision
            for decision in decisions
            if (
                set(decision["outcomes"]) == set(agents)
                and decision["chosen_agent_id"] is not None
            )
        ]

        observed = [
            decision["outcomes"][
                decision["chosen_agent_id"]
            ]
            for decision in usable
        ]

        subset_accuracy = (
            sum(row["correct"] for row in observed)
            / len(observed)
            if observed else None
        )

        results.append({
            "mode": mode,
            "seed": seed,
            "evaluation": evaluation,
            "traces": traces,
            "selected_accuracy": (
                subset_accuracy
                if len(observed) == len(decisions)
                else None
            ),
            "observed_subset_accuracy": subset_accuracy,
        })

    return {
        "new_model_calls": 0,
        "weights": registry.utility.artifact["weights"],
        "utility_sha256": registry.utility.fingerprint,
        "split": next(iter(patient_splits.values())),
        "decisions": len(grouped),
        "results": results,
        "interpretation": (
            "Replay, not fresh LLM evaluation. "
            "Oracle uses available complete candidate outcomes. "
            "Abstentions and missing costs retain incomplete coverage. "
            "Random seeds are repetitions, not new patients."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)

    for name in ("outcomes", "registry", "utility"):
        parser.add_argument(
            "--" + name,
            type=Path,
            required=True,
        )

    parser.add_argument(
        "--seeds",
        nargs="+",
        type=int,
        default=[0, 1, 2],
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
    )

    args = parser.parse_args()

    def read(path):
        return json.loads(
            path.read_text(encoding="utf-8")
        )

    registry = AgentRegistry(
        read(args.registry),
        read(args.utility),
    )

    result = compare(
        read(args.outcomes),
        registry,
        args.seeds,
    )

    result["input_sha256"] = {
        name: hashlib.sha256(
            getattr(args, name).read_bytes()
        ).hexdigest()
        for name in (
            "outcomes",
            "registry",
            "utility",
        )
    }

    args.output_dir.mkdir(
        parents=True,
        exist_ok=False,
    )

    (
        args.output_dir / "comparison.json"
    ).write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )

    lines = [
        "# Routing baseline comparison",
        "",
        result["interpretation"],
        "",
        "| Router | Seed | Coverage | Mean regret "
        "| Selected accuracy |",
        "|---|---:|---:|---:|---:|",
    ]

    for row in result["results"]:
        lines.append(
            f"| {row['mode']} | {row['seed']} "
            f"| {row['evaluation']['coverage']} "
            f"| {row['evaluation']['mean_regret']} "
            f"| {row['selected_accuracy']} |"
        )

    (
        args.output_dir / "comparison.md"
    ).write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    print(
        "Routing replay complete; no model calls: "
        f"{args.output_dir}"
    )


if __name__ == "__main__":
    main()
