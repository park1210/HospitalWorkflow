"""RuleSimilarityRouter estimator baseline; scores are NOT calibrated probabilities."""
from copy import deepcopy
import hashlib
import json
import math
import re


def observed_tokens(observation):
    texts = [observation.get("chief_complaint", ""), *observation.get("current_symptoms", []),
             *observation.get("objective_findings", [])]
    texts += [r.get("answer", "") for r in observation.get("history", []) if r.get("answer_status") != "unknown"]
    texts += [r["text"] for r in observation.get("longitudinal_memory", {}).get("records", [])
              if r.get("status_as_of_visit") != "superseded"]
    return sorted(set(re.findall(r"\w+", " ".join(map(str, texts)).casefold())))


def nonnegative(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


class RoutingUtility:
    def __init__(self, artifact, registry):
        if artifact.get("schema_version") != 1 or artifact.get("method") != "jaccard_beta_v1":
            raise ValueError("Unsupported routing utility artifact")
        if artifact.get("registry") != registry.snapshot():
            raise ValueError("Routing model registry/version mismatch")
        if set(artifact.get("weights", {})) != {"accuracy", "cost", "latency"} or not all(
                nonnegative(v) for v in artifact["weights"].values()) or artifact["weights"]["accuracy"] <= 0:
            raise ValueError("Utility requires nonnegative weights and positive accuracy weight")
        if type(artifact.get("min_samples")) is not int or artifact["min_samples"] < 1:
            raise ValueError("min_samples must be positive")
        self.artifact = deepcopy(artifact)
        if not artifact.get("samples"):
            raise ValueError("No training outcomes")
        agents = {a["agent_id"] for a in artifact["registry"]["agents"] if a["role"] == "specialty"}
        seen = set()
        groups = {}
        for r in artifact["samples"]:
            if (r.get("agent_id") not in agents or type(r.get("correct")) is not bool
                    or any(not nonnegative(r.get(k)) for k in ("cost", "latency_seconds"))
                    or any(not isinstance(r.get(k), str) or not r[k] for k in ("patient_id", "decision_id"))
                    or not isinstance(r.get("tokens"), list) or any(not isinstance(t, str) for t in r["tokens"])):
                raise ValueError("Invalid training outcome")
            key = (r["patient_id"], r["decision_id"], r["agent_id"])
            if key in seen:
                raise ValueError("Duplicate training outcome")
            seen.add(key)
            group = groups.setdefault((r["patient_id"], r["decision_id"]), [])
            group.append(r)
        for group in groups.values():
            if {r["agent_id"] for r in group} != agents or any(r["tokens"] != group[0]["tokens"] for r in group):
                raise ValueError("Training needs all registered specialties on the same observation per decision")
        self.training_patients = {r["patient_id"] for r in artifact["samples"]}
        self.fingerprint = hashlib.sha256(json.dumps(artifact, sort_keys=True).encode()).hexdigest()

    def score(self, observation, agent):
        tokens = set(observed_tokens(observation))
        matches = []
        for r in self.artifact["samples"]:
            if r["agent_id"] != agent["agent_id"]:
                continue
            other = set(r["tokens"])
            similarity = len(tokens & other) / len(tokens | other) if tokens | other else 0
            if similarity > 0:
                matches.append((similarity, r))
        if len(matches) < self.artifact["min_samples"]:
            return None
        weight = sum(w for w, _ in matches)
        probability = (1 + sum(w * r["correct"] for w, r in matches)) / (2 + weight)
        cost = sum(w * r["cost"] for w, r in matches) / weight
        latency = sum(w * r["latency_seconds"] for w, r in matches) / weight
        # Keep artifact/API compatibility; cost and latency are audit-only.
        return {"score": probability, "utility": probability,
                "score_semantics": "uncalibrated_similarity_weighted_outcomes",
                "estimated_correct": probability, "estimated_cost": cost, "estimated_latency_seconds": latency,
                "matched_samples": len(matches), "effective_weight": weight}


def fit_utility(rows, registry, *, weights=None, min_samples=2):
    # Outcome collection must use a separate patient split from evaluation.
    samples = []
    for row in rows:
        if row.get("split") != "train":
            raise ValueError("Only explicitly train-labelled outcomes can fit the router")
        agent = next((a for a in registry.snapshot()["agents"] if a["agent_id"] == row["agent_id"]), None)
        if agent is None or any(row.get(k, agent[k]) != agent[k] for k in ("model", "version")):
            raise ValueError("Outcome model/version does not match registry")
        samples.append({k: row[k] for k in ("patient_id", "decision_id", "agent_id", "correct", "cost", "latency_seconds")})
        samples[-1]["tokens"] = observed_tokens(row["observation"])
    artifact = {"schema_version": 1, "method": "jaccard_beta_v1", "registry": registry.snapshot(),
                "weights": weights or {"accuracy": 1.0, "cost": 0.0, "latency": 0.0},
                "min_samples": min_samples, "samples": samples}
    RoutingUtility(artifact, registry)
    return artifact
