
"""Held-out accuracy-only routing evaluation.

Regret uses correctness only.
Abstained and incomplete decisions have no measurable regret.
"""


def decisions_from_outcomes(outcomes, registry):
    """Convert held-out outcomes into adaptive routing decisions."""
    if registry.utility is None:
        raise ValueError("Fitted routing model required")

    groups = {}
    agents = [
        agent
        for agent in registry.snapshot()["agents"]
        if agent["role"] == "specialty"
    ]
    by_id = {a["agent_id"]: a for a in agents}

    for row in outcomes:
        if row.get("split") not in {"validation", "test"}:
            raise ValueError("Held-out split required")

        if row["patient_id"] in registry.utility.training_patients:
            raise ValueError("Train/evaluation patient overlap")

        key = (row["patient_id"], row["decision_id"])
        groups.setdefault(key, []).append(row)

    decisions = []

    for (patient, decision_id), rows in groups.items():
        seen_agents = set()

        reference = rows[0]["observation"]

        for row in rows:
            agent_id = row["agent_id"]

            if agent_id in seen_agents:
                raise ValueError("Duplicate candidate outcome")
            seen_agents.add(agent_id)

            if agent_id not in by_id:
                raise ValueError("Unknown candidate agent")

            agent = by_id[agent_id]
            if any(
                row.get(k, agent[k]) != agent[k]
                for k in ("model", "version")
            ):
                raise ValueError("Model/version mismatch")

            if row["observation"] != reference:
                raise ValueError(
                    "Candidates must share an observation"
                )

            if type(row.get("correct")) is not bool:
                raise ValueError("Correct must be boolean")

        route = registry.route(
            reference,
            [a["department"] for a in agents],
            mode="adaptive",
        )

        status = route["decision_status"]
        selected_department = route["selected_specialty"]

        chosen = None
        if status == "selected":
            chosen = registry.get(
                "specialty", selected_department
            )["agent_id"]

        decisions.append({
            "patient_id": patient,
            "decision_id": decision_id,
            "candidate_agent_ids": [
                a["agent_id"] for a in agents
            ],
            "chosen_agent_id": chosen,
            "decision_status": status,
            "status": (
                "router_selected"
                if chosen is not None
                else "router_abstained"
            ),
            "outcomes": {
                row["agent_id"]: {
                    "correct": row["correct"],
                }
                for row in rows
            },
        })

    return decisions


def evaluate_routing(decisions, utility):
    """Measure regret and coverage on complete candidate outcomes."""
    registered = {
        agent["agent_id"]
        for agent in utility.artifact["registry"]["agents"]
        if agent["role"] == "specialty"
    }

    seen = set()
    rows = []

    for row in decisions:
        patient_id = row["patient_id"]
        decision_id = row["decision_id"]
        key = (patient_id, decision_id)

        if key in seen:
            raise ValueError("Duplicate evaluation decision")
        seen.add(key)

        if patient_id in utility.training_patients:
            raise ValueError("Train/evaluation patient overlap")

        candidates = row["candidate_agent_ids"]
        chosen = row.get("chosen_agent_id")

        if (
            not candidates
            or len(set(candidates)) != len(candidates)
            or not set(candidates) <= registered
        ):
            raise ValueError("Invalid candidate agent IDs")

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
                    "Abstained decision cannot select an agent"
                )

            rows.append({
                "patient_id": patient_id,
                "decision_id": decision_id,
                "regret": None,
                "oracle_match": None,
                "status": "router_abstained",
            })
            continue

        if status != "selected" or chosen not in candidates:
            raise ValueError("Invalid selected decision")

        outcomes = row.get("outcomes", {})

        if set(outcomes) != set(candidates):
            rows.append({
                "patient_id": patient_id,
                "decision_id": decision_id,
                "regret": None,
                "oracle_match": None,
                "status": "missing_counterfactuals",
            })
            continue

        scores = {}

        for agent_id, outcome in outcomes.items():
            if type(outcome.get("correct")) is not bool:
                raise ValueError("Invalid correctness outcome")

            scores[agent_id] = int(outcome["correct"])

        best = max(scores.values())
        selected_score = scores[chosen]

        rows.append({
            "patient_id": patient_id,
            "decision_id": decision_id,
            "regret": float(best - selected_score),
            "oracle_match": selected_score == best,
            "status": "available",
        })

    valid = [
        row for row in rows
        if row["regret"] is not None
    ]

    subset_regret = (
        sum(row["regret"] for row in valid) / len(valid)
        if valid else None
    )

    return {
        "decisions": rows,
        "coverage": (
            len(valid) / len(rows)
            if rows else None
        ),
        "mean_regret": (
            subset_regret
            if len(valid) == len(rows) and valid
            else None
        ),
        "observed_subset_regret": subset_regret,
        "abstention_count": sum(
            row["status"] == "router_abstained"
            for row in rows
        ),
        "evaluated_count": len(valid),
        "total_count": len(rows),
        "score_semantics": "correctness_only",
    }
