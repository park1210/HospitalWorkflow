"""One-step Bayesian action values; IG and heuristic selection remain distinct."""
from copy import deepcopy
import json
import random
import math
from app.core.diagnostic_belief import posterior, entropy, terminal_choice, DiagnosisBelief, validation_utility
from app.core.information_outcomes import InformationOutcomes, normalized


ACTION_NAMES = {"ask_patient": "Ask", "request_test": "Test",
                "consult_specialty": "Consult", "diagnose": "Diagnose"}


def candidate_actions(runtime, actions, tests, departments, artifact=None):
    """Shared interface; targets are source catalogs, never hidden result text."""
    encounter = "index_encounter_id" in runtime.case_data
    asked = {q["question"] for q in runtime.question_history}
    questions = [e["target"] for e in runtime.case_data.get("current_encounter_events", [])
                 if e["action"] == "Ask" and e["available_minute"] <= runtime.current_time_min
                 and e["target"] not in asked]
    targets = {"ask_patient": questions if encounter else [None],
               "request_test": tests, "consult_specialty": departments,
               "diagnose": [None]}
    result = []
    for kind in actions:
        for target in targets.get(kind, []):
            model = next((a for a in (artifact or {}).get("actions", [])
                          if a["type"] == kind and a["target"] == target), None)
            result.append({"action_id": model["id"] if model else json.dumps([kind, target]),
                           "type": ACTION_NAMES[kind], "action": kind, "target": target,
                           "cost": deepcopy(model["cost"]) if model else (0 if kind == "diagnose" else None),
                           "outcome_model": model["id"] if model else None})
    return result


def action_values(belief, actions, artifact):
    utility, weights = artifact["terminal_utility"], artifact["cost_weights"]
    diagnoses = tuple(belief)

    def cost(action):
        return sum(weights[k] * action["cost"][k] for k in weights)

    for action in actions:
        if any(set(o["likelihood"]) != set(belief) or any(
                type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1
                for p in o["likelihood"].values()) for o in action["outcomes"]):
            raise ValueError("Invalid outcome likelihood")
        if any(not math.isclose(sum(o["likelihood"][d] for o in action["outcomes"]), 1.0,
                                abs_tol=1e-9, rel_tol=0) for d in belief):
            raise ValueError("Outcome likelihoods must sum to one per diagnosis")
        if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0
               for v in [*weights.values(), *action["cost"].values()]):
            raise ValueError("Costs and cost weights must be finite nonnegative")

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
            expected += mass * terminal_choice(updated, utility)[1]
            conditional_entropy += mass * entropy(updated)
            branches.append({"outcome_id": outcome["id"], "probability": mass, "posterior": updated})
        penalty = cost(action)
        results.append({"action_id": action["id"], "expected_continuation_utility": expected,
                        "q_value": expected - penalty,
                        "cost_penalty": penalty, "cost_components": deepcopy(action["cost"]),
                        "voi": expected - baseline - penalty,
                        "information_gain_nats": max(0.0, entropy(belief) - conditional_entropy), "outcomes": branches})
    return sorted(results, key=lambda row: (-row["voi"], row["action_id"]))


def select_action(candidates, *, selector, belief=None, artifact=None, specialist_proposal=None, seed=0):
    """Common selector contract. Missing models produce no numeric Bayesian values."""
    status = {"selector": selector, "status": "available", "selected_action": None}
    if selector == "specialist_heuristic":
        status["selected_action"] = specialist_proposal
        return status
    if selector == "random":
        status["selected_action"] = random.Random(seed).choice(candidates) if candidates else None
        return status
    if selector not in {"bayesian_voi", "information_gain"}:
        raise ValueError("Unknown action selector")
    if artifact is None or belief is None:
        return {**status, "status": "unavailable", "reason": "missing_outcome_model"}
    DiagnosisBelief(belief)
    modeled = {a["id"]: a for a in artifact["actions"]}
    if any(c["type"] != "Diagnose" and c.get("outcome_model") not in modeled for c in candidates):
        return {**status, "status": "unavailable", "reason": "missing_action_outcome_model"}
    utility = artifact.get("terminal_utility")
    if utility is None:
        utility = validation_utility(belief)
    evaluation = {**artifact, "terminal_utility": utility}
    diagnosis, baseline = terminal_choice(belief, utility)
    values = action_values(belief, [modeled[c["outcome_model"]] for c in candidates if c["type"] != "Diagnose"], evaluation)
    lookup = {v["action_id"]: v for v in values}
    ranked = []
    for candidate in candidates:
        if candidate["type"] == "Diagnose":
            row = {**candidate, "target": diagnosis, "q_value": baseline, "information_gain_nats": 0.0}
        else:
            row = {**candidate, **lookup[candidate["outcome_model"]]}
        ranked.append(row)
    metric = "q_value" if selector == "bayesian_voi" else "information_gain_nats"
    ranked.sort(key=lambda r: (-r[metric], r["type"] != "Diagnose", r["action_id"]))
    return {**status, "selected_action": ranked[0] if ranked else None, "values": ranked,
            "diagnose_value": baseline, "utility_scope": "supplied" if artifact.get("terminal_utility") else "algorithm_validation_only"}


class InformationPolicy:
    def __init__(self, artifact, selector="bayesian_voi"):
        self.model = InformationOutcomes(artifact)
        self.selector = selector

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
            state.update(belief=belief, diagnosis_belief=DiagnosisBelief(belief).snapshot(),
                         matched_outcomes=matched, belief_status="valid")
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
                    available = (not state.get("memory_retrieved")
                                 and runtime.voi_memory_pool.get("mode", "none") != "none")
                if available:
                    candidates.append(action)
            interface = [{"action_id": a["id"], "type": ACTION_NAMES.get(a["type"], "Memory"),
                          "action": a["type"], "target": a["target"], "cost": a["cost"],
                          "outcome_model": a["id"]} for a in candidates]
            interface.append({"action_id": "diagnose", "type": "Diagnose", "action": "diagnose",
                              "target": None, "cost": 0, "outcome_model": None})
            # Do not silently compare only the modeled subset of source-backed actions.
            public = candidate_actions(runtime, actions, tests, departments, artifact)
            trace["candidate_scope"] = "source_events" if "index_encounter_id" in runtime.case_data else "legacy_model_catalog"
            if "index_encounter_id" in runtime.case_data and any(c["type"] != "Diagnose" and c["outcome_model"] is None
                   and not (c["type"] == "Ask" and c["target"] is None
                            and any(a["type"] == "ask_patient" for a in candidates)) for c in public):
                trace.update(status="unavailable", selector=self.selector, reason="missing_action_outcome_model")
                state["selector_status"] = deepcopy(trace)
                return None
            selection = select_action(interface, selector=self.selector, belief=belief, artifact=artifact)
            state["selector_status"] = deepcopy(selection)
            trace.update(selector=self.selector, baseline_terminal_utility=baseline,
                         candidates=selection["values"], horizon=1)
            best = selection["selected_action"]
            if best["type"] == "Diagnose":
                trace.update(cost_penalty=0.0, q_value=baseline, stop_reason="diagnose_argmax",
                             model_diagnosis=choice, clinical_support=bool(indices))
                return result("diagnose", choice if indices else "Unresolved",
                              f"Diagnose maximizes {self.selector} action comparison; terminal value={baseline:.6f}.",
                              "supported" if indices else "unresolved")
            selected = next(a for a in candidates if a["id"] == best["action_id"])
            trace.update(action_id=selected["id"], cost_penalty=best["cost_penalty"], cost_components=best["cost_components"], voi=best["voi"])
            rationale = f"{self.selector} selected action: Q={best['q_value']:.6f}; IG={best['information_gain_nats']:.6f}; VoI={best['voi']:.6f}."
            return result(selected["type"], selected["target"], rationale)
        except ValueError as exc:
            state["belief_status"] = "unsupported_observation"
            state["diagnosis_belief"] = DiagnosisBelief(reason="unsupported_observation").snapshot()
            state.pop("belief", None)
            trace.update(status="unavailable", selector=self.selector, reason="unsupported_observation", rationale=str(exc))
            state["selector_status"] = deepcopy(trace)
            return None
