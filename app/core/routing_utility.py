
"""Accuracy-only adaptive specialty routing.

Supports legacy jaccard_beta_v1 artifacts without using
their cost, latency, or weights.

New artifacts use jaccard_beta_accuracy_v2.
"""

from copy import deepcopy
import hashlib
import json
import math
import re


METHOD_V1 = "jaccard_beta_v1"
METHOD_V2 = "jaccard_beta_accuracy_v2"


def nonnegative(value):
    """Legacy-compatible numeric validator."""
    return (
        type(value) in (int, float)
        and math.isfinite(value)
        and value >= 0
    )


def observed_tokens(observation):
    """Extract only doctor-observable information."""
    if not isinstance(observation, dict):
        raise ValueError("Observation must be a dictionary")

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

    for row in observation.get(
        "longitudinal_memory", {}
    ).get("records", []):
        if (
            isinstance(row, dict)
            and row.get("status_as_of_visit") != "superseded"
        ):
            texts.append(row.get("text", ""))

    combined = " ".join(str(value) for value in texts)

    return sorted(
        set(re.findall(r"\w+", combined.casefold()))
    )


def jaccard_similarity(first, second):
    first = set(first)
    second = set(second)

    union = first | second
    if not union:
        return 0.0

    return len(first & second) / len(union)


def _validate_samples(samples, registry):
    if not isinstance(samples, list) or not samples:
        raise ValueError("Nonempty training samples required")

    agents = {
        a["agent_id"]
        for a in registry.snapshot()["agents"]
        if a["role"] == "specialty"
    }

    seen = set()
    groups = {}

    for row in samples:
        if not isinstance(row, dict):
            raise ValueError("Invalid training sample")

        required = {
            "patient_id", "decision_id",
            "agent_id", "correct", "tokens",
        }

        if not required <= set(row):
            raise ValueError("Missing training sample fields")

        if (
            row["agent_id"] not in agents
            or type(row["correct"]) is not bool
            or not isinstance(row["patient_id"], str)
            or not row["patient_id"]
            or not isinstance(row["decision_id"], str)
            or not row["decision_id"]
            or not isinstance(row["tokens"], list)
            or any(
                not isinstance(token, str)
                for token in row["tokens"]
            )
        ):
            raise ValueError("Invalid training sample")

        key = (
            row["patient_id"],
            row["decision_id"],
            row["agent_id"],
        )
        if key in seen:
            raise ValueError("Duplicate training sample")
        seen.add(key)

        group_key = key[:2]
        groups.setdefault(group_key, []).append(row)

    for group in groups.values():
        if (
            {r["agent_id"] for r in group} != agents
            or any(
                r["tokens"] != group[0]["tokens"]
                for r in group
            )
        ):
            raise ValueError(
                "Training requires the same observation "
                "and all registered specialty outcomes"
            )


class RoutingUtility:
    """Similarity-weighted correctness estimator."""

    def __init__(self, artifact, registry):
        if not isinstance(artifact, dict):
            raise ValueError("Invalid routing artifact")

        if (
            artifact.get("schema_version") not in {1, 2}
            or artifact.get("method")
            not in {METHOD_V1, METHOD_V2}
        ):
            raise ValueError("Unsupported routing artifact")

        if artifact.get("registry") != registry.snapshot():
            raise ValueError("Registry/version mismatch")

        min_samples = artifact.get("min_samples")
        if type(min_samples) is not int or min_samples < 1:
            raise ValueError("Invalid min_samples")

        _validate_samples(artifact.get("samples"), registry)

        # Retain the supplied artifact for audit and hashing.
        # Legacy costs and weights are never used in selection.
        self.artifact = deepcopy(artifact)

        self.training_patients = {
            row["patient_id"]
            for row in artifact["samples"]
        }

        self.fingerprint = hashlib.sha256(
            json.dumps(
                artifact,
                sort_keys=True,
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()

    def score(self, observation, agent):
        """Estimate correctness, or return None for no support."""
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

        total_weight = sum(weight for weight, _ in matches)

        estimated_correct = (
            1.0
            + sum(
                weight * int(row["correct"])
                for weight, row in matches
            )
        ) / (2.0 + total_weight)

        return {
            "score": estimated_correct,
            "utility": estimated_correct,
            "estimated_correct": estimated_correct,
            "score_semantics": (
                "uncalibrated_similarity_weighted_correctness"
            ),
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
    """Fit an accuracy-only model from train patients.

    weights is retained only to detect incompatible callers.
    """
    if weights is not None:
        if weights != {"accuracy": 1.0, "cost": 0.0, "latency": 0.0}:
            raise ValueError(
                "Cost/latency weights are no longer supported. "
                "Use accuracy-only routing."
            )

    samples = []

    for row in rows:
        if row.get("split") != "train":
            raise ValueError("Only train rows can fit routing")

        agent = next(
            (
                a for a in registry.snapshot()["agents"]
                if a["agent_id"] == row.get("agent_id")
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
            raise ValueError("Invalid agent/model binding")

        if type(row.get("correct")) is not bool:
            raise ValueError("Correct must be boolean")

        sample = {
            "patient_id": row["patient_id"],
            "decision_id": row["decision_id"],
            "agent_id": row["agent_id"],
            "correct": row["correct"],
            "tokens": observed_tokens(row["observation"]),
        }
        samples.append(sample)

    artifact = {
        "schema_version": 2,
        "method": METHOD_V2,
        "registry": registry.snapshot(),
        "min_samples": min_samples,
        "samples": samples,
    }

    RoutingUtility(artifact, registry)
    return artifact
