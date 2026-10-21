"""Finite diagnostic beliefs; exact Bayes updates, no inferred clinical rates."""
from __future__ import annotations
import math
from dataclasses import dataclass


@dataclass
class DiagnosisBelief:
    """Explicit model-derived belief; absence is not a uniform prior."""
    probabilities: dict | None = None
    status: str = "unavailable"
    reason: str | None = "missing_outcome_model"

    def __post_init__(self):
        if self.probabilities is not None:
            self.probabilities = distribution(self.probabilities)
            self.status, self.reason = "available", None

    def snapshot(self):
        return {"probabilities": None if self.probabilities is None else dict(self.probabilities),
                "status": self.status, "reason": self.reason}


def validation_utility(diagnoses, correct=1.0, incorrect=0.0):
    """Configurable algorithm-validation utility ONLY, not clinical utility."""
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in (correct, incorrect)):
        raise ValueError("Utility values must be finite")
    return {choice: {d: correct if d == choice else incorrect for d in diagnoses} for choice in diagnoses}


def distribution(values, keys=None):
    if not isinstance(values, dict) or not values or (keys is not None and set(values) != set(keys)):
        raise ValueError("Probability keys must match diagnoses")
    if any(type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1 for p in values.values()):
        raise ValueError("Probabilities must be finite values in [0,1]")
    if not math.isclose(sum(values.values()), 1.0, abs_tol=1e-9, rel_tol=0):
        raise ValueError("Probabilities must sum to one")
    return dict(values)


def posterior(prior, likelihood):
    distribution(prior)
    if set(likelihood) != set(prior) or any(type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1 for p in likelihood.values()):
        raise ValueError("Invalid likelihood")
    weights = {d: prior[d] * likelihood[d] for d in prior}
    mass = sum(weights.values())
    if mass <= 0:
        raise ValueError("Observed outcome has zero probability under this model")
    return {d: p / mass for d, p in weights.items()}, mass


def entropy(belief):
    distribution(belief)
    return -sum(p * math.log(p) for p in belief.values() if p > 0)


def terminal_choice(belief, utility):
    distribution(belief)
    if not utility or any(set(row) != set(belief) or any(
            type(v) not in (int, float) or not math.isfinite(v) for v in row.values()) for row in utility.values()):
        raise ValueError("Utility must contain finite values for every diagnosis")
    scores = {choice: sum(belief[d] * row[d] for d in belief) for choice, row in utility.items()}
    chosen = min(scores, key=lambda choice: (-scores[choice], choice))
    return chosen, scores[chosen]
