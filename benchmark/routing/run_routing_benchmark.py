
"""Run independent Routing Benchmark policies.

Example:
  python -m benchmark.routing.run_routing_benchmark \
    --cases benchmark/routing/data/pilot.json \
    --registry app/data/agent_registry.example.json \
    --output-dir results/routing_pilot
"""

import argparse
import csv
import hashlib
import json
from copy import deepcopy
from pathlib import Path

from app.core.agent_registry import AgentRegistry

from benchmark.routing.validate_routing_gold import (
    validate_routing_gold,
)
from benchmark.routing.evaluate_routing_benchmark import (
    evaluate_routing_benchmark,
)


def _without_memory(observation):
    cleaned = deepcopy(observation)
    cleaned.pop("longitudinal_memory", None)
    return cleaned


def _strip_nonobservable_fields(observation):
    """Allow only fields supported by routing policies."""
    allowed = {
        "chief_complaint",
        "current_symptoms",
        "vital_signs",
        "history",
        "objective_findings",
        "longitudinal_memory",
    }

    return {
        key: deepcopy(value)
        for key, value in observation.items()
        if key in allowed
    }


def run_routing_benchmark(
    cases,
    registry,
    *,
    modes=("rule", "random", "adaptive"),
    random_seed=0,
    llm_router=None,
    memory_router=None,
):
    """Run common-input routing baselines.

    LLM routers are optional preconfigured LLMRouter objects.
    No gold labels are supplied to any router.
    """
    validate_routing_gold(cases)

    supported_modes = {
        "rule",
        "random",
        "adaptive",
        "llm",
        "memory_aware_llm",
    }

    if (
        not modes
        or len(set(modes)) != len(modes)
        or not set(modes) <= supported_modes
    ):
        raise ValueError("Invalid routing modes")

    if "adaptive" in modes and registry.utility is None:
        raise ValueError(
            "Adaptive routing requires a fitted utility artifact"
        )

    if "llm" in modes and llm_router is None:
        raise ValueError("LLM router client required")

    if (
        "memory_aware_llm" in modes
        and memory_router is None
    ):
        raise ValueError("Memory-aware LLM router required")

    if registry.utility is not None:
        overlap = {
            case["patient_id"]
            for case in cases
        } & registry.utility.training_patients

        if overlap:
            raise ValueError(
                "Routing training/evaluation patient overlap: "
                + ", ".join(sorted(overlap))
            )

    available = {
        agent["department"]
        for agent in registry.snapshot()["agents"]
        if agent["role"] == "specialty"
    }

    for case in cases:
        unknown = (
            set(case["candidate_departments"])
            - available
        )
        if unknown:
            raise ValueError(
                "Unregistered candidate departments: "
                + ", ".join(sorted(unknown))
            )

    predictions = {}
    audit_log = []

    for mode in modes:
        predictions[mode] = {}

        for case in cases:
            case_id = case["case_id"]
            departments = case["candidate_departments"]

            # Gold, labels, source data and hidden future
            # observations are deliberately excluded.
            observation = _strip_nonobservable_fields(
                case["observation"]
            )

            if mode != "memory_aware_llm":
                observation = _without_memory(observation)

            audit = []
            if mode == "llm":
                result = llm_router.select(
                    observation,
                    departments,
                    audit=audit,
                )
            elif mode == "memory_aware_llm":
                result = memory_router.select(
                    observation,
                    departments,
                    audit=audit,
                )
            else:
                result = registry.route(
                    observation,
                    departments,
                    mode=mode,
                    seed=random_seed,
                )

            selected = result.get("selected_specialty")

            if mode in {"llm", "memory_aware_llm"}:
                status = (
                    "selected"
                    if result.get("status") == "available"
                    and selected is not None
                    else "unavailable"
                )
            else:
                status = result.get(
                    "decision_status", "unavailable"
                )

            predictions[mode][case_id] = {
                "decision_status": status,
                "selected_specialty": (
                    selected
                    if status == "selected"
                    else None
                ),
            }

            audit_log.append({
                "case_id": case_id,
                "policy": mode,
                "decision_status": status,
                "selected_specialty": selected,
                "specialty_scores": result.get(
                    "specialty_scores", {}
                ),
                "rationale": result.get("rationale"),
                "model_audit": audit,
            })

    evaluation = evaluate_routing_benchmark(
        cases,
        predictions,
    )

    evaluation["predictions"] = predictions
    evaluation["audit"] = audit_log
    evaluation["modes"] = list(modes)
    evaluation["random_seed"] = random_seed

    evaluation["utility_sha256"] = (
        registry.utility.fingerprint
        if registry.utility else None
    )

    return evaluation


def main():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--cases", type=Path, required=True
    )
    parser.add_argument(
        "--registry", type=Path, required=True
    )
    parser.add_argument(
        "--utility", type=Path
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        default=["rule", "random"],
        choices=["rule", "random", "adaptive"],
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
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

    cases = read(args.cases)
    manifest = read(args.registry)

    registry = AgentRegistry(
        manifest,
        read(args.utility) if args.utility else None,
    )

    result = run_routing_benchmark(
        cases,
        registry,
        modes=tuple(args.modes),
        random_seed=args.seed,
    )

    result["input_sha256"] = {
        "cases": hashlib.sha256(
            args.cases.read_bytes()
        ).hexdigest(),
        "registry": hashlib.sha256(
            args.registry.read_bytes()
        ).hexdigest(),
        "utility": (
            hashlib.sha256(
                args.utility.read_bytes()
            ).hexdigest()
            if args.utility else None
        ),
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

    summary_rows = []

    for item in result["summary"]:
        summary_rows.append({
            key: item[key]
            for key in (
                "policy",
                "cases",
                "selected",
                "abstained",
                "unavailable",
                "failed",
                "coverage",
                "selective_accuracy",
                "overall_success_rate",
                "primary_accuracy",
                "macro_f1",
            )
        })

    with (
        args.output_dir / "summary.csv"
    ).open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=list(summary_rows[0]),
        )
        writer.writeheader()
        writer.writerows(summary_rows)

    lines = [
        "# Routing Benchmark Comparison",
        "",
        "| Policy | Coverage | Selective Accuracy "
        "| Overall Success | Macro-F1 |",
        "|---|---:|---:|---:|---:|",
    ]

    for row in summary_rows:
        lines.append(
            f"| {row['policy']} "
            f"| {row['coverage']:.4f} "
            f"| {row['selective_accuracy']} "
            f"| {row['overall_success_rate']:.4f} "
            f"| {row['macro_f1']} |"
        )

    (
        args.output_dir / "comparison.md"
    ).write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    print(
        "Routing Benchmark complete: "
        f"{args.output_dir}"
    )


if __name__ == "__main__":
    main()
