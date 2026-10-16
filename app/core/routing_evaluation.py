"""Held-out full-information regret; missing outcomes remain unevaluated."""
from app.core.routing_utility import nonnegative


def decisions_from_outcomes(outcomes, registry):
    """Recompute the router on held-out observations; oracle results stay separate."""
    import json
    groups = {}
    for row in outcomes:
        if row["split"] not in {"validation", "test"}:
            raise ValueError("Evaluation requires held-out outcomes")
        groups.setdefault((row["patient_id"], row["decision_id"]), []).append(row)
    decisions = []
    agents = [a for a in registry.snapshot()["agents"] if a["role"] == "specialty"]
    for (patient, decision), rows in groups.items():
        if len({r["agent_id"] for r in rows}) != len(rows):
            raise ValueError("Duplicate candidate outcomes")
        if any(json.dumps(r["observation"], sort_keys=True) != json.dumps(rows[0]["observation"], sort_keys=True) for r in rows):
            raise ValueError("Counterfactual probes must share an identical observation")
        if registry.utility is None or patient in registry.utility.training_patients:
            raise ValueError("Need fitted router and disjoint evaluation patients")
        route = registry.route(rows[0]["observation"], [a["department"] for a in agents], mode="adaptive")
        if len(route["allowed_departments"]) != 1:
            # No autonomous choice under insufficient training coverage.
            decisions.append({"patient_id": patient, "decision_id": decision,
                              "candidate_agent_ids": [a["agent_id"] for a in agents],
                              "chosen_agent_id": None, "outcomes": {}, "status": "router_abstained"})
            continue
        chosen = registry.get("specialty", route["allowed_departments"][0])["agent_id"]
        for row in rows:
            agent = next((a for a in agents if a["agent_id"] == row["agent_id"]), None)
            if agent is None or any(row.get(k, agent[k]) != agent[k] for k in ("model", "version")):
                raise ValueError("Counterfactual model/version mismatch")
        decisions.append({"patient_id": patient, "decision_id": decision,
                          "candidate_agent_ids": [a["agent_id"] for a in agents], "chosen_agent_id": chosen,
                          "outcomes": {r["agent_id"]: {k: r[k] for k in ("correct", "cost", "latency_seconds")}
                                       for r in rows if r.get("cost") is not None}})
    return decisions


def evaluate_routing(decisions, utility):
    rows = []
    seen = set()
    registered = {a["agent_id"] for a in utility.artifact["registry"]["agents"] if a["role"] == "specialty"}
    for row in decisions:
        if row["patient_id"] in utility.training_patients:
            raise ValueError("Routing evaluation patient overlaps training")
        candidates = row["candidate_agent_ids"]
        key = (row["patient_id"], row["decision_id"])
        if key in seen:
            raise ValueError("Duplicate evaluation decision")
        seen.add(key)
        if row.get("status") == "router_abstained" and row["chosen_agent_id"] is None:
            rows.append({"decision_id": row["decision_id"], "regret": None, "status": "router_abstained"})
            continue
        if (not candidates or len(set(candidates)) != len(candidates) or row["chosen_agent_id"] not in candidates
                or not set(candidates) <= registered):
            raise ValueError("Invalid routing candidate/chosen IDs")
        outcomes = row["outcomes"]
        if set(outcomes) != set(candidates):
            rows.append({"decision_id": row["decision_id"], "regret": None, "status": "missing_counterfactuals"})
            continue
        scores = {}
        for agent_id, result in outcomes.items():
            if type(result.get("correct")) is not bool or any(not nonnegative(result.get(k)) for k in ("cost", "latency_seconds")):
                raise ValueError("Invalid oracle outcome")
            w = utility.artifact["weights"]
            scores[agent_id] = w["accuracy"] * result["correct"] - w["cost"] * result["cost"] - w["latency"] * result["latency_seconds"]
        best = max(scores.values())
        rows.append({"decision_id": row["decision_id"], "regret": best - scores[row["chosen_agent_id"]],
                     "oracle_match": scores[row["chosen_agent_id"]] == best, "status": "available"})
    valid = [r for r in rows if r["regret"] is not None]
    return {"decisions": rows, "coverage": len(valid) / len(rows) if rows else None,
            "mean_regret": sum(r["regret"] for r in valid) / len(valid) if valid and len(valid) == len(rows) else None,
            "observed_subset_regret": sum(r["regret"] for r in valid) / len(valid) if valid else None}
