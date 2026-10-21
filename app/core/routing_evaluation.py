
"""Held-out specialty routing evaluation.

Abstentions have no observed regret.
Counterfactual regret is evaluated only with complete outcomes.
"""

import json

from app.core.routing_utility import nonnegative


def decisions_from_outcomes(outcomes, registry):
    """Recompute routing on held-out observations.

    The routing policy never receives oracle correctness labels.
    """
    groups = {}

    for row in outcomes:
        if row["split"] not in {"validation", "test"}:
            raise ValueError(
                "Evaluation requires held-out outcomes"
            )

        key = (
            row["patient_id"],
            row["decision_id"],
        )
        groups.setdefault(key, []).append(row)

    decisions = []

    agents = [
        agent
        for agent in registry.snapshot()["agents"]
        if agent["role"] == "specialty"
    ]

    agent_by_id = {
        agent["agent_id"]: agent
        for agent in agents
    }

    for (patient, decision), rows in groups.items():
        if (
            registry.utility is None
            or patient in registry.utility.training_patients
        ):
            raise ValueError(
                "Need fitted router and disjoint evaluation patients"
            )

        if len({
            row["agent_id"]
            for row in rows
        }) != len(rows):
            raise ValueError(
                "Duplicate candidate outcomes"
            )

        reference_observation = json.dumps(
            rows[0]["observation"],
            sort_keys=True,
        )

        for row in rows:
            if (
                json.dumps(
                    row["observation"],
                    sort_keys=True,
                ) != reference_observation
            ):
                raise ValueError(
                    "Counterfactual probes must share "
                    "an identical observation"
                )

            agent = agent_by_id.get(
                row["agent_id"]
            )

            if (
                agent is None
                or any(
                    row.get(field, agent[field])
                    != agent[field]
                    for field in ("model", "version")
                )
            ):
                raise ValueError(
                    "Counterfactual model/version mismatch"
                )

        route = registry.route(
            rows[0]["observation"],
            [
                agent["department"]
                for agent in agents
            ],
            mode="adaptive",
        )

        candidate_ids = [
            agent["agent_id"]
            for agent in agents
        ]

        # Decide whether a router actually selected a
        # specialty, rather than inferring from menu size.
        if (
            route.get("decision_status") != "selected"
            or route.get("selected_specialty") is None
        ):
            decisions.append({
                "patient_id": patient,
                "decision_id": decision,
                "candidate_agent_ids": candidate_ids,
                "chosen_agent_id": None,
                "outcomes": {},
                "status": "router_abstained",
                "decision_status": route.get(
                    "decision_status", "abstained"
                ),
            })
            continue

        selected_department = route[
            "selected_specialty"
        ]

        chosen = registry.get(
            "specialty",
            selected_department,
        )["agent_id"]

        decisions.append({
            "patient_id": patient,
            "decision_id": decision,
            "candidate_agent_ids": candidate_ids,
            "chosen_agent_id": chosen,
            "outcomes": {
                row["agent_id"]: {
                    key: row[key]
                    for key in (
                        "correct",
                        "cost",
                        "latency_seconds",
                    )
                }
                for row in rows
                if row.get("cost") is not None
            },
            "status": "router_selected",
            "decision_status": "selected",
        })

    return decisions


def evaluate_routing(decisions, utility):
    """Evaluate full-information routing regret and coverage."""
    rows = []
    seen = set()

    registered = {
        agent["agent_id"]
        for agent in utility.artifact["registry"]["agents"]
        if agent["role"] == "specialty"
    }

    for row in decisions:
        patient = row["patient_id"]
        decision_id = row["decision_id"]

        if patient in utility.training_patients:
            raise ValueError(
                "Routing evaluation patient overlaps training"
            )

        key = (patient, decision_id)

        if key in seen:
            raise ValueError(
                "Duplicate evaluation decision"
            )

        seen.add(key)

        candidates = row["candidate_agent_ids"]
        chosen = row.get("chosen_agent_id")

        if (
            not candidates
            or len(set(candidates)) != len(candidates)
            or not set(candidates) <= registered
        ):
            raise ValueError(
                "Invalid routing candidate IDs"
            )

        status = row.get(
            "decision_status",
            (
                "abstained"
                if row.get("status") == "router_abstained"
                else "selected"
            ),
        )

        if status in {"abstained", "unavailable"}:
            if chosen is not None:
                raise ValueError(
                    "Abstained routing must not have "
                    "a selected specialist"
                )

            rows.append({
                "decision_id": decision_id,
                "regret": None,
                "oracle_match": None,
                "status": "router_abstained",
            })
            continue

        if status != "selected" or chosen not in candidates:
            raise ValueError(
                "Invalid routing choice or decision status"
            )

        outcomes = row["outcomes"]

        if set(outcomes) != set(candidates):
            rows.append({
                "decision_id": decision_id,
                "regret": None,
                "oracle_match": None,
                "status": "missing_counterfactuals",
            })
            continue

        weights = utility.artifact["weights"]
        scores = {}

        for agent_id, result in outcomes.items():
            if (
                type(result.get("correct")) is not bool
                or any(
                    not nonnegative(result.get(field))
                    for field in (
                        "cost",
                        "latency_seconds",
                    )
                )
            ):
                raise ValueError(
                    "Invalid oracle outcome"
                )

            scores[agent_id] = (
                weights["accuracy"] * float(result["correct"])
                - weights["cost"] * result["cost"]
                - weights["latency"]
                * result["latency_seconds"]
            )

        best = max(scores.values())

        rows.append({
            "decision_id": decision_id,
            "regret": best - scores[chosen],
            "oracle_match": scores[chosen] == best,
            "status": "available",
        })

    valid = [
        row
        for row in rows
        if row["regret"] is not None
    ]

    coverage = (
        len(valid) / len(rows)
        if rows else None
    )

    observed_subset_regret = (
        sum(row["regret"] for row in valid) / len(valid)
        if valid else None
    )

    return {
        "decisions": rows,
        "coverage": coverage,
        "mean_regret": (
            observed_subset_regret
            if valid and len(valid) == len(rows)
            else None
        ),
        "observed_subset_regret": observed_subset_regret,
        "abstention_count": sum(
            row["status"] == "router_abstained"
            for row in rows
        ),
        "evaluated_count": len(valid),
        "total_count": len(rows),
    }
