
"""Independent action-selection evaluation for the VoI benchmark.

This evaluator uses externally reviewed action labels.
It does not generate gold labels from VoI predictions.
It does not claim that action agreement proves clinical utility.

Run:
    python -m benchmark.voi.evaluate_action_choices \
        --input benchmark/voi/data/pilot.json \
        --output-dir results/voi_pilot
"""

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


VALID_SPLITS = {"validation", "test"}
VALID_STATUSES = {"selected", "abstained", "unavailable"}


def mean(values):
    return sum(values) / len(values) if values else None


def validate_case(case):
    required = {
        "case_id",
        "patient_id",
        "split",
        "available_actions",
        "gold",
        "predictions",
    }

    if not isinstance(case, dict) or not required <= set(case):
        raise ValueError("Missing VoI benchmark case fields")

    if any(
        not isinstance(case[field], str) or not case[field].strip()
        for field in ("case_id", "patient_id")
    ):
        raise ValueError("Invalid case or patient ID")

    if case["split"] not in VALID_SPLITS:
        raise ValueError(
            "Benchmark evaluation requires validation/test cases"
        )

    actions = case["available_actions"]

    if not isinstance(actions, list) or not actions:
        raise ValueError("Available actions must be nonempty")

    action_ids = []

    for action in actions:
        if not isinstance(action, dict):
            raise ValueError("Invalid action")

        if not isinstance(action.get("id"), str) or not action["id"]:
            raise ValueError("Action ID required")

        if action.get("type") not in {
            "ask_patient",
            "request_test",
            "consult_specialty",
            "retrieve_memory",
            "diagnose",
        }:
            raise ValueError("Unsupported action type")

        action_ids.append(action["id"])

    if len(set(action_ids)) != len(action_ids):
        raise ValueError("Duplicate action ID")

    allowed = set(action_ids)
    gold = case["gold"]

    if not isinstance(gold, dict):
        raise ValueError("Gold must be a dictionary")

    if gold.get("review_status") != "reviewed":
        raise ValueError(
            "Only independently reviewed gold labels are evaluated"
        )

    if not isinstance(gold.get("review_reference"), str) or not gold["review_reference"].strip():
        raise ValueError("Gold review reference required")

    acceptable = gold.get("acceptable_action_ids")
    unnecessary = gold.get("unnecessary_action_ids")

    if not isinstance(acceptable, list) or not acceptable:
        raise ValueError("At least one acceptable action is required")

    if not isinstance(unnecessary, list):
        raise ValueError("Unnecessary action IDs must be a list")

    if (
        len(set(acceptable)) != len(acceptable)
        or len(set(unnecessary)) != len(unnecessary)
    ):
        raise ValueError("Duplicate gold action IDs")

    if not set(acceptable) <= allowed:
        raise ValueError("Gold references unavailable actions")

    if not set(unnecessary) <= allowed:
        raise ValueError("Unnecessary action references unknown actions")

    if set(acceptable) & set(unnecessary):
        raise ValueError(
            "Acceptable and unnecessary actions overlap"
        )

    predictions = case["predictions"]

    if not isinstance(predictions, dict) or not predictions:
        raise ValueError("At least one policy prediction is required")

    for policy, prediction in predictions.items():
        if not isinstance(policy, str) or not policy:
            raise ValueError("Invalid policy name")

        if not isinstance(prediction, dict):
            raise ValueError("Invalid prediction")

        status = prediction.get("status")
        selected = prediction.get("selected_action_id")

        if status not in VALID_STATUSES:
            raise ValueError("Invalid prediction status")

        if status == "selected":
            if selected not in allowed:
                raise ValueError(
                    "Selected action must belong to available actions"
                )
        elif selected is not None:
            raise ValueError(
                "Abstained/unavailable prediction must not select an action"
            )


def evaluate(cases):
    if not isinstance(cases, list) or not cases:
        raise ValueError("Nonempty case list required")

    seen = set()
    patient_splits = {}
    policy_names = None
    rows = []

    for case in cases:
        validate_case(case)

        case_id = case["case_id"]
        patient_id = case["patient_id"]
        split = case["split"]

        if case_id in seen:
            raise ValueError("Duplicate benchmark case ID")

        seen.add(case_id)

        if (
            patient_id in patient_splits
            and patient_splits[patient_id] != split
        ):
            raise ValueError(
                "A patient cannot appear in multiple evaluation splits"
            )

        patient_splits[patient_id] = split

        current_policies = set(case["predictions"])

        if policy_names is None:
            policy_names = current_policies
        elif current_policies != policy_names:
            raise ValueError(
                "Every case must have predictions from identical policies"
            )

        actions = {
            action["id"]: action
            for action in case["available_actions"]
        }

        acceptable = set(
            case["gold"]["acceptable_action_ids"]
        )
        unnecessary = set(
            case["gold"]["unnecessary_action_ids"]
        )

        for policy, prediction in case["predictions"].items():
            selected = prediction["selected_action_id"]
            status = prediction["status"]

            made_choice = status == "selected"
            correct = (
                selected in acceptable
                if made_choice else None
            )

            is_unnecessary = (
                selected in unnecessary
                if made_choice else None
            )

            is_unnecessary_test = (
                is_unnecessary
                and actions[selected]["type"] == "request_test"
                if made_choice else None
            )

            rows.append({
                "case_id": case_id,
                "patient_id": patient_id,
                "split": split,
                "policy": policy,
                "status": status,
                "selected_action_id": selected,
                "selected_action_type": (
                    actions[selected]["type"]
                    if made_choice else None
                ),
                "correct": correct,
                "unnecessary_action": is_unnecessary,
                "unnecessary_test": is_unnecessary_test,
                "gold_acceptable_ids": sorted(acceptable),
            })

    grouped = defaultdict(list)

    for row in rows:
        grouped[row["policy"]].append(row)

    summary = []

    for policy, group in sorted(grouped.items()):
        selected = [
            row for row in group
            if row["status"] == "selected"
        ]

        selected_tests = [
            row for row in selected
            if row["selected_action_type"] == "request_test"
        ]

        correct_selected = sum(
            row["correct"] for row in selected
        )

        total = len(group)

        summary.append({
            "policy": policy,
            "cases": total,
            "selected_count": len(selected),
            "abstained_count": sum(
                row["status"] == "abstained"
                for row in group
            ),
            "unavailable_count": sum(
                row["status"] == "unavailable"
                for row in group
            ),
            "coverage": len(selected) / total,
            "selective_accuracy": (
                correct_selected / len(selected)
                if selected else None
            ),
            "overall_success_rate": correct_selected / total,
            "unnecessary_action_rate": (
                sum(row["unnecessary_action"] for row in selected)
                / len(selected)
                if selected else None
            ),
            "unnecessary_test_rate": (
                sum(
                    row["unnecessary_test"]
                    for row in selected_tests
                ) / len(selected_tests)
                if selected_tests else None
            ),
        })

    return {
        "schema_version": 1,
        "evaluation_type": "offline_action_selection",
        "case_count": len(cases),
        "summary": summary,
        "rows": rows,
        "interpretation": (
            "Metrics measure agreement with independently reviewed "
            "action labels. They do not measure counterfactual "
            "clinical outcome, treatment benefit, or causal VoI. "
            "Unnecessary-action rates only reflect explicitly "
            "reviewed unnecessary-action labels."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--input",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
    )

    args = parser.parse_args()

    cases = json.loads(
        args.input.read_text(encoding="utf-8")
    )

    result = evaluate(cases)

    args.output_dir.mkdir(
        parents=True,
        exist_ok=False,
    )

    (
        args.output_dir / "results.json"
    ).write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )

    with (
        args.output_dir / "summary.csv"
    ).open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as output:
        writer = csv.DictWriter(
            output,
            fieldnames=list(result["summary"][0]),
        )
        writer.writeheader()
        writer.writerows(result["summary"])

    print(
        "VoI action-selection evaluation complete: "
        f"{args.output_dir}"
    )


if __name__ == "__main__":
    main()
