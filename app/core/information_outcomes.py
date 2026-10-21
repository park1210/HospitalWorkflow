"""Auditable finite outcome model, with exact matching of released observations."""
from copy import deepcopy
import hashlib
import json
import math
from app.core.diagnostic_belief import distribution, posterior, validation_utility
from app.utils.department_catalog import SUPPORTED_DEPARTMENTS


def normalized(text):
    return " ".join(str(text).casefold().split())


class InformationOutcomes:
    def __init__(self, artifact):
        artifact = deepcopy(artifact)
        if isinstance(artifact, dict) and artifact.get("terminal_utility") is None and artifact.get("diagnoses"):
            artifact["terminal_utility"] = validation_utility(artifact["diagnoses"])
            artifact.setdefault("provenance", {})["utility_scope"] = "algorithm_validation_only"
        # Legacy fields remain readable, but neither determines action selection.
        if isinstance(artifact, dict):
            artifact.setdefault("stop_probability", 0.95)
            artifact.setdefault("horizon", 1)
        required = {"schema_version", "model_id", "revision", "provenance", "diagnoses", "prior", "terminal_utility",
                    "cost_weights", "stop_probability", "horizon", "actions"}
        if not isinstance(artifact, dict) or set(artifact) != required or artifact["schema_version"] != 1:
            raise ValueError("Invalid VoI model fields")
        for key in ("model_id", "revision"):
            if not isinstance(artifact[key], str) or not artifact[key].strip():
                raise ValueError("Explicit VoI model identity/version required")
        provenance = artifact["provenance"]
        if (not isinstance(provenance, dict) or type(provenance.get("synthetic")) is not bool
                or provenance.get("review_status") not in {"unreviewed", "expert_reviewed"}
                or not provenance.get("assumptions")):
            raise ValueError("VoI provenance and assumptions required")
        if provenance["review_status"] == "expert_reviewed" and not all(provenance.get(k) for k in ("reviewer", "review_reference")):
            raise ValueError("Expert review requires reviewer and review reference")
        patients = provenance.get("training_patients", [])
        if (not isinstance(patients, list) or any(not isinstance(p, str) or not p for p in patients)
                or len(set(patients)) != len(patients)):
            raise ValueError("Training patient IDs must be unique strings")
        diagnoses = artifact["diagnoses"]
        if not isinstance(diagnoses, dict) or not 2 <= len(diagnoses) <= 32 or any(
                not isinstance(d, str) or not d.strip() or department not in SUPPORTED_DEPARTMENTS for d, department in diagnoses.items()):
            raise ValueError("Need 2..32 diagnosis labels and canonical departments")
        distribution(artifact["prior"], diagnoses)
        utility = artifact["terminal_utility"]
        if set(utility) != set(diagnoses) or any(set(row) != set(diagnoses) or any(
                type(v) not in (float, int) or not math.isfinite(v) for v in row.values()) for row in utility.values()):
            raise ValueError("Terminal utilities must specify every choice/true-diagnosis pair")
        weights = artifact["cost_weights"]
        if set(weights) != {"money", "minutes", "tokens"} or any(
                type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in weights.values()):
            raise ValueError("Cost conversion weights must be finite nonnegative")
        threshold = artifact["stop_probability"]
        if type(threshold) not in (int, float) or not .5 < threshold <= 1:
            raise ValueError("Stop threshold must be > .5 and <= 1")
        if type(artifact["horizon"]) is not int or not 1 <= artifact["horizon"] <= 3:
            raise ValueError("Planning horizon must be 1..3")
        if not isinstance(artifact["actions"], list) or not 1 <= len(artifact["actions"]) <= 12:
            raise ValueError("Provide 1..12 information actions")
        ids, bindings, signatures = set(), set(), set()
        sources = {"request_test": "objective_findings", "ask_patient": "history", "consult_specialty": "consults", "retrieve_memory": "memory"}
        for action in artifact["actions"]:
            if set(action) != {"id", "type", "target", "cost", "outcomes"} or action["type"] not in sources:
                raise ValueError("Invalid information action")
            if any(not isinstance(action[k], str) or not action[k].strip() for k in ("id", "target")):
                raise ValueError("Action ID and target required")
            if action["id"] in ids or (action["type"], action["target"]) in bindings:
                raise ValueError("Duplicate action ID or binding")
            ids.add(action["id"])
            bindings.add((action["type"], action["target"]))
            if action["type"] == "consult_specialty" and action["target"] not in SUPPORTED_DEPARTMENTS:
                raise ValueError("Consult target must be canonical")
            if action["type"] == "ask_patient" and not action["target"].endswith(("?", "？")):
                raise ValueError("Question target must end with ?")
            if action["type"] == "retrieve_memory" and action["target"] != "longitudinal":
                raise ValueError("Only longitudinal memory acquisition is supported")
            if set(action["cost"]) != set(weights) or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in action["cost"].values()):
                raise ValueError("Action costs must explicitly include money/minutes/tokens")
            outcomes = action["outcomes"]
            if not isinstance(outcomes, list) or not 2 <= len(outcomes) <= 8:
                raise ValueError("Need 2..8 categorical outcomes per action")
            outcome_ids = set()
            for outcome in outcomes:
                if set(outcome) != {"id", "likelihood", "observation", "supports_diagnoses"}:
                    raise ValueError("Invalid outcome fields")
                if not isinstance(outcome["id"], str) or not outcome["id"] or outcome["id"] in outcome_ids:
                    raise ValueError("Unique outcome IDs required")
                outcome_ids.add(outcome["id"])
                likelihood = outcome["likelihood"]
                if set(likelihood) != set(diagnoses) or any(type(p) not in (float, int) or not math.isfinite(p) or not 0 <= p <= 1 for p in likelihood.values()):
                    raise ValueError("Likelihood must define P(outcome|diagnosis,action)")
                obs = outcome["observation"]
                if (set(obs) != {"source", "text"} or obs["source"] != sources[action["type"]]
                        or not isinstance(obs["text"], str) or not obs["text"].strip()):
                    raise ValueError("Outcome observation must match the action's released source")
                signature = (obs["source"], normalized(obs["text"]))
                if signature in signatures:
                    raise ValueError("Observation text must not count as two independent outcomes")
                signatures.add(signature)
                support = outcome["supports_diagnoses"]
                if not isinstance(support, list) or not set(support) <= set(diagnoses) or (support and obs["source"] != "objective_findings"):
                    raise ValueError("Only explicit current objective outcomes may support finalization")
            for d in diagnoses:
                if not math.isclose(sum(o["likelihood"][d] for o in outcomes), 1, abs_tol=1e-9, rel_tol=0):
                    raise ValueError("Outcome likelihoods must sum to one for each diagnosis/action")
        self.artifact = deepcopy(artifact)
        self.fingerprint = hashlib.sha256(json.dumps(artifact, sort_keys=True).encode()).hexdigest()

    def observe(self, observation):
        belief, matched = dict(self.artifact["prior"]), []
        for action in self.artifact["actions"]:
            kind, target = action["type"], action["target"]
            texts = []
            if kind == "request_test":
                texts = [t for t in observation.get("objective_findings", []) if str(t).startswith(target + ":")]
            elif kind == "ask_patient":
                texts = [r.get("answer", "") for r in observation.get("history", [])
                         if r.get("question") == target and r.get("answer_status") != "unknown"]
            elif kind == "consult_specialty":
                texts = [r.get("opinion", "") for r in observation.get("consults", []) if r.get("department") == target]
            elif kind == "retrieve_memory":
                texts = [r["text"] for r in observation.get("longitudinal_memory", {}).get("records", [])
                         if r.get("status_as_of_visit") != "superseded"]
            found = [o for o in action["outcomes"] if normalized(o["observation"]["text"]) in {normalized(t) for t in texts}]
            if len(found) > 1:
                raise ValueError("Conflicting outcome observations; conditional-independent model not applicable")
            if texts and not found:
                raise ValueError("Released outcome is outside the supplied categorical model")
            if found:
                belief, mass = posterior(belief, found[0]["likelihood"])
                matched.append({"action_id": action["id"], "outcome_id": found[0]["id"], "predictive_probability": mass,
                                "observation": deepcopy(found[0]["observation"]), "supports_diagnoses": found[0]["supports_diagnoses"]})
        return belief, matched
