"""Finite-horizon expected utility of information, separate from safety gates."""
from copy import deepcopy
from functools import lru_cache
from app.core.diagnostic_belief import posterior, entropy, terminal_choice
from app.core.information_outcomes import InformationOutcomes, normalized


def action_values(belief, actions, artifact):
    utility, weights = artifact["terminal_utility"], artifact["cost_weights"]
    lookup = {a["id"]: a for a in actions}
    diagnoses = tuple(belief)
    nodes = [0]

    def cost(action):
        return sum(weights[k] * action["cost"][k] for k in weights)

    @lru_cache(maxsize=5000)
    def value(probabilities, remaining, depth):
        nodes[0] += 1
        if nodes[0] > 5000:
            raise ValueError("VoI planning node budget exceeded; reduce horizon/actions")
        current = dict(zip(diagnoses, probabilities))
        best = terminal_choice(current, utility)[1]
        if depth:
            for key in remaining:
                action = lookup[key]
                expected = -cost(action)
                for outcome in action["outcomes"]:
                    mass = sum(current[d] * outcome["likelihood"][d] for d in diagnoses)
                    if mass <= 0:
                        continue
                    updated, _ = posterior(current, outcome["likelihood"])
                    expected += mass * value(tuple(updated[d] for d in diagnoses), tuple(k for k in remaining if k != key), depth - 1)
                best = max(best, expected)
        return best

    baseline = terminal_choice(belief, utility)[1]
    results = []
    for action in actions:
        expected, conditional_entropy, branches = 0.0, 0.0, []
        for outcome in action["outcomes"]:
            mass = sum(belief[d] * outcome["likelihood"][d] for d in diagnoses)
            if mass <= 0:
                branches.append({"outcome_id": outcome["id"], "probability": 0.0, "posterior": None})
                continue
            updated, _ = posterior(belief, outcome["likelihood"])
            expected += mass * value(tuple(updated[d] for d in diagnoses), tuple(k for k in lookup if k != action["id"]), artifact["horizon"] - 1)
            conditional_entropy += mass * entropy(updated)
            branches.append({"outcome_id": outcome["id"], "probability": mass, "posterior": updated})
        penalty = cost(action)
        results.append({"action_id": action["id"], "expected_continuation_utility": expected,
                        "cost_penalty": penalty, "cost_components": deepcopy(action["cost"]),
                        "voi": expected - baseline - penalty,
                        "information_gain_nats": max(0.0, entropy(belief) - conditional_entropy), "outcomes": branches})
    return sorted(results, key=lambda row: (-row["voi"], row["action_id"]))


class InformationPolicy:
    def __init__(self, artifact):
        self.model = InformationOutcomes(artifact)

    def propose(self, runtime, observed, *, actions, tests, departments, evidence_records, allow_unresolved):
        state = runtime.voi_state
        artifact = self.model.artifact
        if state.get("model_sha256", self.model.fingerprint) != self.model.fingerprint:
            raise ValueError("VoI model changed within a visit")
        state["model_sha256"] = self.model.fingerprint
        trace = {"minute": runtime.current_time_min, "status": "evaluating", "selected_action": None}
        state.setdefault("history", []).append(trace)
        try:
            belief, matched = self.model.observe(observed)
            state.update(belief=belief, matched_outcomes=matched, belief_status="valid")
            trace.update(belief=belief, entropy_nats=entropy(belief), matched_outcomes=matched)
            choice, baseline = terminal_choice(belief, artifact["terminal_utility"])
            supports = {normalized(m["observation"]["text"]) for m in matched if choice in m["supports_diagnoses"]}
            indices = [i for i, e in enumerate(evidence_records) if e["supports_finalization"] and normalized(e["text"]) in supports]
            cited = [r["memory_id"] for r in observed.get("longitudinal_memory", {}).get("records", [])
                     if any(m["observation"]["source"] == "memory" and normalized(r["text"]) == normalized(m["observation"]["text"]) for m in matched)]
            def result(kind, target, rationale, certainty="unresolved"):
                trace.update(status="selected", selected_action=kind, target=target, rationale=rationale)
                return {"action": kind, "target": target, "rationale": rationale, "assessment": f"Model belief: {choice}={belief[choice]:.6f}",
                        "department": artifact["diagnoses"][choice], "certainty": certainty,
                        "evidence_indices": indices if certainty == "supported" else [], "memory_ids": cited}
            if "diagnose" in actions and indices and belief[choice] >= artifact["stop_probability"]:
                trace.update(cost_penalty=0.0, stop_reason="decisive_model_and_objective_evidence")
                return result("diagnose", choice, "Stop: explicit model probability meets threshold and released objective evidence supports this candidate.", "supported")
            if "diagnose" in actions and allow_unresolved:
                trace.update(cost_penalty=0.0, stop_reason="existing_budget_or_action_exhaustion")
                return result("diagnose", "Unresolved", "Stop unresolved: existing decision budget or available-action gate is exhausted.")
            consumed = {m["action_id"] for m in matched}
            candidates = []
            for action in artifact["actions"]:
                kind, target = action["type"], action["target"]
                if action["id"] in consumed:
                    continue
                available = (kind in actions and ((kind == "request_test" and target in tests)
                    or (kind == "consult_specialty" and target in departments)
                    or (kind == "ask_patient" and all(normalized(q["question"]) != normalized(target) for q in runtime.question_history))))
                if kind == "retrieve_memory":
                    available = (not allow_unresolved and not state.get("memory_retrieved")
                                 and runtime.voi_memory_pool.get("mode", "none") != "none")
                if available:
                    candidates.append(action)
            scored = action_values(belief, candidates, artifact)
            trace.update(baseline_terminal_utility=baseline, candidates=scored, horizon=artifact["horizon"])
            if not scored:
                trace.update(status="fallback", rationale="No supported outcome model for remaining available actions; use existing evidence-driven physician policy.")
                return None
            best = scored[0]
            selected = next(a for a in candidates if a["id"] == best["action_id"])
            trace.update(action_id=selected["id"], cost_penalty=best["cost_penalty"], cost_components=best["cost_components"], voi=best["voi"])
            rationale = f"Highest modeled information value among available actions: VoI={best['voi']:.6f}; cost penalty={best['cost_penalty']:.6f}."
            if best["voi"] <= 0:
                rationale += " No admissible supported/unresolved stop exists yet; advance under the existing uncertainty gate."
            return result(selected["type"], selected["target"], rationale)
        except ValueError as exc:
            state["belief_status"] = "unsupported_observation"
            trace.update(status="fallback", rationale=str(exc))
            return None
