
"""Routing Benchmark metrics with explicit abstention handling."""

from collections import defaultdict

from benchmark.routing.validate_routing_gold import (
    validate_routing_gold,
)


def _safe_div(numerator, denominator):
    return (
        numerator / denominator
        if denominator else None
    )


def evaluate_routing_benchmark(cases, predictions):
    """Evaluate predictions from multiple routing policies.

    predictions format:
      {
        "policy_name": {
          "case_id": {
            "decision_status": "selected" | "abstained"
                               | "unavailable" | "failed",
            "selected_specialty": "neurology" | None
          }
        }
      }
    """
    validate_routing_gold(cases)

    if not isinstance(predictions, dict) or not predictions:
        raise ValueError("Policy predictions required")

    by_id = {
        case["case_id"]: case
        for case in cases
    }
    ids = set(by_id)
    policies = sorted(predictions)

    rows = []
    summary = []

    for policy in policies:
        predictions_for_policy = predictions[policy]

        if not isinstance(predictions_for_policy, dict):
            raise ValueError("Invalid policy predictions")

        if set(predictions_for_policy) != ids:
            raise ValueError(
                f"Incomplete prediction coverage: {policy}"
            )

        policy_rows = []
        confusion = defaultdict(
            lambda: defaultdict(int)
        )
        classes = set()

        for case in cases:
            case_id = case["case_id"]
            result = predictions_for_policy[case_id]

            if not isinstance(result, dict):
                raise ValueError("Invalid prediction")

            status = result.get("decision_status")
            selected = result.get("selected_specialty")

            if status not in {
                "selected",
                "abstained",
                "unavailable",
                "failed",
            }:
                raise ValueError(
                    f"Invalid decision status: {case_id}"
                )

            if status == "selected":
                if selected not in case[
                    "candidate_departments"
                ]:
                    raise ValueError(
                        f"Selected specialty not a candidate: {case_id}"
                    )
            elif selected is not None:
                raise ValueError(
                    f"Non-selected status has selection: {case_id}"
                )

            gold = case["gold"]
            primary = gold.get("primary_specialty")
            acceptable = set(
                gold["acceptable_specialties"]
            )

            correct = (
                selected in acceptable
                if status == "selected"
                else False
            )

            primary_correct = (
                selected == primary
                if primary is not None
                else None
            )

            row = {
                "case_id": case_id,
                "patient_id": case["patient_id"],
                "policy": policy,
                "decision_status": status,
                "selected_specialty": selected,
                "primary_gold": primary,
                "acceptable_gold": sorted(acceptable),
                "acceptable_correct": correct,
                "primary_correct": primary_correct,
            }
            policy_rows.append(row)
            rows.append(row)

            if primary is not None:
                classes.add(primary)
                if selected is not None:
                    classes.add(selected)

                predicted_label = (
                    selected
                    if status == "selected"
                    else "__ABSTAIN__"
                )
                confusion[primary][predicted_label] += 1

        total = len(policy_rows)
        selected_rows = [
            row for row in policy_rows
            if row["decision_status"] == "selected"
        ]

        selected_count = len(selected_rows)
        correct_count = sum(
            row["acceptable_correct"]
            for row in selected_rows
        )

        primary_rows = [
            row for row in policy_rows
            if row["primary_gold"] is not None
        ]

        class_metrics = {}
        f1_values = []

        for department in sorted(classes):
            tp = sum(
                row["primary_gold"] == department
                and row["selected_specialty"] == department
                and row["decision_status"] == "selected"
                for row in primary_rows
            )

            fp = sum(
                row["primary_gold"] != department
                and row["selected_specialty"] == department
                and row["decision_status"] == "selected"
                for row in primary_rows
            )

            fn = sum(
                row["primary_gold"] == department
                and (
                    row["selected_specialty"] != department
                    or row["decision_status"] != "selected"
                )
                for row in primary_rows
            )

            precision = (
                tp / (tp + fp)
                if tp + fp else 0.0
            )
            recall = (
                tp / (tp + fn)
                if tp + fn else 0.0
            )
            f1 = (
                2 * precision * recall
                / (precision + recall)
                if precision + recall else 0.0
            )

            class_metrics[department] = {
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "support": tp + fn,
            }
            f1_values.append(f1)

        result = {
            "policy": policy,
            "cases": total,
            "selected": selected_count,
            "abstained": sum(
                row["decision_status"] == "abstained"
                for row in policy_rows
            ),
            "unavailable": sum(
                row["decision_status"] == "unavailable"
                for row in policy_rows
            ),
            "failed": sum(
                row["decision_status"] == "failed"
                for row in policy_rows
            ),
            "coverage": selected_count / total,
            "selective_accuracy": _safe_div(
                correct_count,
                selected_count,
            ),
            "overall_success_rate": correct_count / total,
            "abstention_rate": sum(
                row["decision_status"] == "abstained"
                for row in policy_rows
            ) / total,
            "primary_gold_cases": len(primary_rows),
            "primary_accuracy": _safe_div(
                sum(
                    row["primary_correct"] is True
                    for row in primary_rows
                ),
                len(primary_rows),
            ),
            "macro_f1": _safe_div(
                sum(f1_values),
                len(f1_values),
            ),
            "per_class": class_metrics,
            "confusion_matrix": {
                gold: dict(counts)
                for gold, counts in confusion.items()
            },
        }

        summary.append(result)

    return {
        "schema_version": 1,
        "evaluation_type": "gold_specialty_selection",
        "case_count": len(cases),
        "summary": summary,
        "rows": rows,
        "interpretation": (
            "Primary accuracy and Macro-F1 use cases with "
            "a primary gold label. Acceptable accuracy permits "
            "multiple independently reviewed specialties. "
            "Abstentions are not counted as correct selections."
        ),
    }
