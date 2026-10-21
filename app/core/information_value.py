"""Cost-free Bayesian action values and finite-horizon action selection."""
from copy import deepcopy
import json
import random
from app.core.diagnostic_belief import entropy, terminal_choice, DiagnosisBelief, validation_utility
from app.core.information_outcomes import InformationOutcomes, normalized
from app.core.voi_planning import plan_voi


ACTION_NAMES = {"ask_patient": "Ask", "request_test": "Test",
                "consult_specialty": "Consult", "diagnose": "Diagnose"}


def candidate_actions(runtime, actions, tests, departments, artifact=None):
    """Shared interface; targets are source catalogs, never hidden result text."""
    encounter = "index_encounter_id" in runtime.case_data
    asked = {q["question"] for q in runtime.question_history
             if isinstance(q, dict) and isinstance(q.get("question"), str) and q["question"]}
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
                           "cost": None,
                           "outcome_model": model["id"] if model else None})
    return result


def action_values(belief, actions, artifact):
    """Cost-free one-step expected utility and information gain.

    Historical cost fields are accepted for artifact compatibility but ignored.
    """
    utility = artifact.get("terminal_utility") or validation_utility(belief)
    baseline = terminal_choice(belief, utility)[1]
    plan = plan_voi(belief, actions, utility, horizon=1)
    return [{
        **row,
        "expected_continuation_utility": row["q_value"],
        "cost_penalty": 0.0,
        "cost_components": {},
    } for row in sorted(plan["action_values"], key=lambda r: (-r["voi"], r["action_id"]))]



def select_action(candidates, *, selector, belief=None, artifact=None, specialist_proposal=None, seed=0):
    """Select cost-free VoI or IG while preserving existing candidate contract."""
    status = {"selector": selector, "status": "available", "selected_action": None}
    if selector == "specialist_heuristic":
        return {**status, "selected_action": specialist_proposal}
    if selector == "random":
        return {**status, "selected_action": random.Random(seed).choice(candidates) if candidates else None}
    if selector not in {"bayesian_voi", "information_gain"}:
        raise ValueError("Unknown action selector")
    if artifact is None or belief is None:
        return {**status, "status": "unavailable", "reason": "missing_outcome_model"}
    DiagnosisBelief(belief)
    modeled = {a["id"]: a for a in artifact["actions"]}
    if len(modeled) != len(artifact["actions"]):
        raise ValueError("Duplicate modeled action IDs")
    info_candidates = [c for c in candidates if c["type"] != "Diagnose"]
    if any(c.get("outcome_model") not in modeled for c in info_candidates):
        return {**status, "status": "unavailable", "reason": "missing_action_outcome_model"}
    utility = artifact.get("terminal_utility") or validation_utility(belief)
    diagnosis, baseline = terminal_choice(belief, utility)
    horizon = artifact.get("horizon", 1) if selector == "bayesian_voi" else 1
    selected_models = [modeled[c["outcome_model"]] for c in info_candidates]
    if len({a["id"] for a in selected_models}) != len(selected_models):
        raise ValueError("Duplicate candidate actions")
    plan = plan_voi(belief, selected_models, utility, horizon=horizon)
    lookup = {r["action_id"]: r for r in plan["action_values"]}
    ranked = []
    for candidate in candidates:
        if candidate["type"] == "Diagnose":
            row = {**candidate, "target": diagnosis, "q_value": baseline,
                   "voi": 0.0, "information_gain_nats": 0.0,
                   "cost_penalty": 0.0, "cost_components": {}}
        else:
            row = {**candidate, **lookup[candidate["outcome_model"]],
                   "cost_penalty": 0.0, "cost_components": {}}
        ranked.append(row)
    if selector == "bayesian_voi":
        # Diagnose wins ties: without cost, never force an action of zero marginal value.
        ranked.sort(key=lambda r: (-r["q_value"], r["type"] != "Diagnose", r["action_id"]))
    else:
        ranked.sort(key=lambda r: (-r["information_gain_nats"], r["type"] != "Diagnose", r["action_id"]))
    return {**status, "selected_action": ranked[0] if ranked else None,
            "values": ranked, "diagnose_value": baseline,
            "horizon": horizon, "cost_model": "none",
            "utility_scope": "supplied" if artifact.get("terminal_utility") else "algorithm_validation_only"}



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
            public = candidate_actions(runtime, actions, tests, departments, artifact)
            encounter = "index_encounter_id" in runtime.case_data
            executable = {(c["action"], c["target"]) for c in public}
            candidates = []
            for action in artifact["actions"]:
                kind, target = action["type"], action["target"]
                if action["id"] in consumed:
                    continue
                available = (kind in actions and ((kind == "request_test" and target in tests)
                    or (kind == "consult_specialty" and target in departments)
                    or (kind == "ask_patient" and all(normalized(q.get("question", "")) != normalized(target) for q in runtime.question_history if isinstance(q, dict)))))
                if kind == "retrieve_memory":
                    available = (not state.get("memory_retrieved")
                                 and runtime.voi_memory_pool.get("mode", "none") != "none")
                if encounter:
                    available = available and (kind, target) in executable
                if available:
                    candidates.append(action)
            interface = [{"action_id": a["id"], "type": ACTION_NAMES.get(a["type"], "Memory"),
                          "action": a["type"], "target": a["target"], "cost": None,
                          "outcome_model": a["id"]} for a in candidates]
            interface.append({"action_id": "diagnose", "type": "Diagnose", "action": "diagnose",
                              "target": None, "cost": None, "outcome_model": None})
            # Do not silently compare only the modeled subset of source-backed actions.
            trace["candidate_scope"] = "source_events" if "index_encounter_id" in runtime.case_data else "legacy_model_catalog"
            if "index_encounter_id" in runtime.case_data and any(c["type"] != "Diagnose" and c["outcome_model"] is None
                   and not (c["type"] == "Ask" and c["target"] is None
                            and any(a["type"] == "ask_patient" for a in candidates)) for c in public):
                trace.update(status="unavailable", selector=self.selector, reason="missing_action_outcome_model")
                state["selector_status"] = deepcopy(trace)
                return None
            selection = select_action(interface, selector=self.selector, belief=belief, artifact=artifact)
            state["selector_status"] = deepcopy(selection)
            if selection.get("status") != "available" or selection.get("selected_action") is None:
                trace.update(status="unavailable", selector=self.selector,
                             reason=selection.get("reason", "no_selectable_action"))
                state["selector_status"] = deepcopy(selection)
                return None
            trace.update(selector=self.selector, baseline_terminal_utility=baseline,
                         candidates=selection["values"], horizon=selection["horizon"])
            best = selection["selected_action"]
            if best["type"] == "Diagnose":
                trace.update(cost_penalty=0.0, q_value=baseline, stop_reason="diagnose_argmax",
                             model_diagnosis=choice, clinical_support=bool(indices))
                if not indices and not allow_unresolved:
                    trace.update(status="unavailable", reason="diagnostic_gate_requires_evidence")
                    state["selector_status"] = deepcopy(trace)
                    return None
                return result("diagnose", choice if indices else "Unresolved",
                              f"Diagnose maximizes {self.selector} action comparison; terminal value={baseline:.6f}.",
                              "supported" if indices else "unresolved")
            selected = next(a for a in candidates if a["id"] == best["action_id"])
            trace.update(action_id=selected["id"], voi=best["voi"], planning_horizon=selection["horizon"])
            rationale = f"{self.selector} selected action: Q={best['q_value']:.6f}; IG={best['information_gain_nats']:.6f}; VoI={best['voi']:.6f}."
            return result(selected["type"], selected["target"], rationale)
        except ValueError as exc:
            state["belief_status"] = "unsupported_observation"
            state["diagnosis_belief"] = DiagnosisBelief(reason="unsupported_observation").snapshot()
            state.pop("belief", None)
            trace.update(status="unavailable", selector=self.selector, reason="unsupported_observation", rationale=str(exc))
            state["selector_status"] = deepcopy(trace)
            return None
