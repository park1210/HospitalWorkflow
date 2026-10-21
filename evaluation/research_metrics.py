
"""Common cost-free research evaluation metrics.

All confidence intervals are computed at the patient level.
These metrics do not generate clinical gold annotations.
"""

import math
import random
from collections import defaultdict


def ndcg_at_k(retrieved_ids, relevance, k):
    """Compute NDCG@K from nonnegative graded relevance."""
    if type(k) is not int or k < 1:
        raise ValueError("k must be positive")

    if (
        not isinstance(relevance, dict)
        or any(
            type(value) not in (int, float)
            or not math.isfinite(value)
            or value < 0
            for value in relevance.values()
        )
    ):
        raise ValueError("Invalid relevance grades")

    retrieved = list(retrieved_ids)
    if len(retrieved) != len(set(retrieved)):
        raise ValueError("Duplicate retrieved IDs")

    def gain(value):
        return (2 ** value) - 1

    dcg = sum(
        gain(relevance.get(memory_id, 0))
        / math.log2(index + 1)
        for index, memory_id in enumerate(
            retrieved[:k], start=1
        )
    )

    ideal = sorted(
        relevance.values(),
        reverse=True,
    )[:k]

    idcg = sum(
        gain(value) / math.log2(index + 1)
        for index, value in enumerate(
            ideal, start=1
        )
    )

    return dcg / idcg if idcg > 0 else None


def classification_metrics(
    gold_labels,
    predicted_labels,
    *,
    labels=None,
):
    """Compute accuracy, per-class scores and Macro-F1.

    None predictions are abstentions and count as failures.
    """
    gold = list(gold_labels)
    predicted = list(predicted_labels)

    if not gold or len(gold) != len(predicted):
        raise ValueError("Paired nonempty labels required")

    classes = (
        sorted(set(gold) | {p for p in predicted if p is not None})
        if labels is None
        else list(labels)
    )

    if not set(gold) <= set(classes):
        raise ValueError("Gold label outside class set")

    if not set(p for p in predicted if p is not None) <= set(classes):
        raise ValueError("Prediction outside class set")

    per_class = {}

    for label in classes:
        tp = sum(
            g == label and p == label
            for g, p in zip(gold, predicted)
        )
        fp = sum(
            g != label and p == label
            for g, p in zip(gold, predicted)
        )
        fn = sum(
            g == label and p != label
            for g, p in zip(gold, predicted)
        )

        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0

        f1 = (
            2 * precision * recall / (precision + recall)
            if precision + recall else 0.0
        )

        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": tp + fn,
        }

    selected = sum(p is not None for p in predicted)
    correct = sum(
        g == p for g, p in zip(gold, predicted)
    )

    return {
        "count": len(gold),
        "accuracy": correct / len(gold),
        "coverage": selected / len(gold),
        "selective_accuracy": (
            correct / selected if selected else None
        ),
        "macro_f1": (
            sum(row["f1"] for row in per_class.values())
            / len(per_class)
            if per_class else None
        ),
        "per_class": per_class,
    }


def risk_coverage_curve(confidences, correct):
    """Risk-coverage curve for a confidence-ranked selector.

    Confidence must be a finite numeric score, not
    necessarily a calibrated probability.
    """
    if (
        not confidences
        or len(confidences) != len(correct)
    ):
        raise ValueError("Paired confidence/correctness required")

    rows = []

    for index, (confidence, outcome) in enumerate(
        zip(confidences, correct)
    ):
        if (
            type(confidence) not in (int, float)
            or not math.isfinite(confidence)
            or type(outcome) is not bool
        ):
            raise ValueError("Invalid risk-coverage input")

        rows.append((confidence, index, int(outcome)))

    rows.sort(key=lambda row: (-row[0], row[1]))

    n = len(rows)
    errors = 0
    points = [{"coverage": 0.0, "risk": 0.0}]

    for count, (_, _, outcome) in enumerate(
        rows, start=1
    ):
        errors += 1 - outcome

        points.append({
            "coverage": count / n,
            "risk": errors / count,
        })

    # Trapezoidal area under the risk-coverage curve.
    aurc = sum(
        (
            points[i - 1]["risk"] + points[i]["risk"]
        ) / 2
        * (
            points[i]["coverage"]
            - points[i - 1]["coverage"]
        )
        for i in range(1, len(points))
    )

    return {
        "points": points,
        "aurc": aurc,
        "definition": "trapezoidal_risk_coverage_area",
    }


def paired_bootstrap_ci(
    patient_ids,
    baseline_scores,
    candidate_scores,
    *,
    repetitions=2000,
    seed=42,
    confidence=0.95,
):
    """Patient-cluster bootstrap CI for candidate minus baseline.

    Scores should represent paired case-level measurements.
    """
    if (
        not patient_ids
        or not (
            len(patient_ids)
            == len(baseline_scores)
            == len(candidate_scores)
        )
    ):
        raise ValueError("Paired observations required")

    if (
        type(repetitions) is not int
        or repetitions < 100
        or not 0 < confidence < 1
    ):
        raise ValueError("Invalid bootstrap settings")

    groups = defaultdict(list)

    for patient, before, after in zip(
        patient_ids,
        baseline_scores,
        candidate_scores,
    ):
        if (
            not isinstance(patient, str)
            or not patient
            or any(
                type(v) not in (int, float)
                or not math.isfinite(v)
                for v in (before, after)
            )
        ):
            raise ValueError("Invalid paired score")

        groups[patient].append(after - before)

    patients = sorted(groups)
    rng = random.Random(seed)

    observed = sum(
        value
        for rows in groups.values()
        for value in rows
    ) / len(patient_ids)

    estimates = []

    for _ in range(repetitions):
        sampled_patients = rng.choices(
            patients,
            k=len(patients),
        )

        differences = [
            value
            for patient in sampled_patients
            for value in groups[patient]
        ]

        estimates.append(
            sum(differences) / len(differences)
        )

    estimates.sort()

    alpha = 1 - confidence
    lower_index = max(
        0,
        math.floor(repetitions * alpha / 2),
    )
    upper_index = min(
        repetitions - 1,
        math.ceil(repetitions * (1 - alpha / 2)) - 1,
    )

    return {
        "difference": observed,
        "lower": estimates[lower_index],
        "upper": estimates[upper_index],
        "confidence": confidence,
        "repetitions": repetitions,
        "patients": len(patients),
        "method": "patient_cluster_percentile_bootstrap",
    }
