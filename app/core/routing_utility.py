
"""Adaptive specialty-routing utility estimation.

Uses patient-disjoint training outcomes and Jaccard similarity.
Estimated correctness is not a calibrated probability.
"""

from copy import deepcopy
import hashlib
import json
import math
import re


DEFAULT_WEIGHTS = {
    "accuracy": 1.0,
    "cost": 0.0,
    "latency": 0.0,
}


def observed_tokens(observation):
    """Tokenize only observable information."""
    if not isinstance(observation, dict):
        raise ValueError("observation must be a dictionary")

    texts = [
        observation.get("chief_complaint", ""),
        *observation.get("current_symptoms", []),
        *observation.get("objective_findings", []),
    ]

    for row in observation.get("history", []):
        if (
            isinstance(row, dict)
            and row.get("answer_status") != "unknown"
        ):
            texts.append(row.get("answer", ""))

    memory = observation.get("longitudinal_memory", {})

    for row in memory.get("records", []):
        if (
            isinstance(row, dict)
            and row.get("status_as_of_visit") != "superseded"
        ):
            texts.append(row.get("text", ""))

    combined = " ".join(str(value) for value in texts)

    return sorted(
        set(re.findall(r"\w+", combined.casefold()))
    )


def nonnegative(value):
    return (
        type(value) in (int, float)
        and math.isfinite(value)
        and value >= 0
    )


def jaccard_similarity(first, second):
    first = set(first)
    second = set(second)

    union = first | second

    if not union:
        return 0.0

    return len(first & second) / len(union)


class RoutingUtility:
    """Fitted routing estimator based on historical outcomes."""

    def __init__(self, artifact, registry):
        if not isinstance(artifact, dict):
            raise ValueError("Invalid routing artifact")

        if (
            artifact.get("schema_version") != 1
            or artifact.get("method") != "jaccard_beta_v1"
        ):
            raise ValueError(
                "Unsupported routing utility artifact"
            )

        if artifact.get("registry") != registry.snapshot():
            raise ValueError(
                "Routing model registry/version mismatch"
            )

        weights = artifact.get("weights", {})

        if (
            set(weights) != {"accuracy", "cost", "latency"}
            or not all(
                nonnegative(value)
                for value in weights.values()
            )
            or weights["accuracy"] <= 0
        ):
            raise ValueError(
                "Utility requires nonnegative weights "
                "and positive accuracy weight"
            )

        min_samples = artifact.get("min_samples")

        if type(min_samples) is not int or min_samples < 1:
            raise ValueError(
                "min_samples must be a positive integer"
            )

        samples = artifact.get("samples")

        if not isinstance(samples, list) or not samples:
            raise ValueError("No training outcomes")

        self.artifact = deepcopy(artifact)

        agents = {
            agent["agent_id"]
            for agent in artifact["registry"]["agents"]
            if agent["role"] == "specialty"
        }

        seen = set()
        groups = {}

        for row in samples:
            if (
                row.get("agent_id") not in agents
                or type(row.get("correct")) is not bool
                or any(
                    not nonnegative(row.get(field))
                    for field in ("cost", "latency_seconds")
                )
                or any(
                    not isinstance(row.get(field), str)
                    or not row[field]
                    for field in ("patient_id", "decision_id")
                )
                or not isinstance(row.get("tokens"), list)
                or any(
                    not isinstance(token, str)
                    for token in row["tokens"]
                )
            ):
                raise ValueError(
                    "Invalid training outcome"
                )

            key = (
                row["patient_id"],
                row["decision_id"],
                row["agent_id"],
            )

            if key in seen:
                raise ValueError(
                    "Duplicate training outcome"
                )

            seen.add(key)

            group_key = (
                row["patient_id"],
                row["decision_id"],
            )

            groups.setdefault(group_key, []).append(row)

        for group in groups.values():
            if (
                {row["agent_id"] for row in group} != agents
                or any(
                    row["tokens"] != group[0]["tokens"]
                    for row in group
                )
            ):
                raise ValueError(
                    "Training needs all registered specialties "
                    "on the same observation per decision"
                )

        self.training_patients = {
            row["patient_id"]
            for row in samples
        }

        self.fingerprint = hashlib.sha256(
            json.dumps(
                artifact,
                sort_keys=True,
            ).encode()
        ).hexdigest()

    def score(self, observation, agent):
        """Estimate utility for one specialist.

        Returns None when training support is insufficient.
        """
        tokens = set(observed_tokens(observation))

        matches = []

        for row in self.artifact["samples"]:
            if row["agent_id"] != agent["agent_id"]:
                continue

            similarity = jaccard_similarity(
                tokens,
                row["tokens"],
            )

            if similarity > 0:
                matches.append((similarity, row))

        if len(matches) < self.artifact["min_samples"]:
            return None

        total_weight = sum(
            weight
            for weight, _ in matches
        )

        # Beta(1, 1) smoothed estimate.
        estimated_correct = (
            1.0
            + sum(
                weight * float(row["correct"])
                for weight, row in matches
            )
        ) / (2.0 + total_weight)

        estimated_cost = sum(
            weight * row["cost"]
            for weight, row in matches
        ) / total_weight

        estimated_latency = sum(
            weight * row["latency_seconds"]
            for weight, row in matches
        ) / total_weight

        weights = self.artifact["weights"]

        utility = (
            weights["accuracy"] * estimated_correct
            - weights["cost"] * estimated_cost
            - weights["latency"] * estimated_latency
        )

        return {
            "score": utility,
            "utility": utility,
            "score_semantics": (
                "uncalibrated_expected_utility"
            ),
            "estimated_correct": estimated_correct,
            "estimated_cost": estimated_cost,
            "estimated_latency_seconds": estimated_latency,
            "matched_samples": len(matches),
            "effective_weight": total_weight,
        }


def fit_utility(
    rows,
    registry,
    *,
    weights=None,
    min_samples=2,
):
    """Fit a routing artifact from training-only outcomes."""
    samples = []

    for row in rows:
        if row.get("split") != "train":
            raise ValueError(
                "Only explicitly train-labelled outcomes "
                "can fit the router"
            )

        agent = next(
            (
                item
                for item in registry.snapshot()["agents"]
                if item["agent_id"] == row["agent_id"]
            ),
            None,
        )

        if (
            agent is None
            or agent["role"] != "specialty"
            or any(
                row.get(field, agent[field]) != agent[field]
                for field in ("model", "version")
            )
        ):
            raise ValueError(
                "Outcome model/version does not match registry"
            )

        sample = {
            key: row[key]
            for key in (
                "patient_id",
                "decision_id",
                "agent_id",
                "correct",
                "cost",
                "latency_seconds",
            )
        }

        sample["tokens"] = observed_tokens(
            row["observation"]
        )

        samples.append(sample)

    effective_weights = (
        deepcopy(DEFAULT_WEIGHTS)
        if weights is None
        else deepcopy(weights)
    )

    artifact = {
        "schema_version": 1,
        "method": "jaccard_beta_v1",
        "registry": registry.snapshot(),
        "weights": effective_weights,
        "min_samples": min_samples,
        "samples": samples,
    }

    # Enforce artifact validation before returning.
    RoutingUtility(artifact, registry)

    return artifact
