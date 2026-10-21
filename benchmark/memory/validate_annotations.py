
"""Validate memory benchmark gold annotations."""

from app.core.longitudinal_memory import (
    PatientMemoryStore,
    visit_identity,
)
from app.core.memory_evaluation import visit_key


def validate_memory_gold(cases, memory, annotations):
    store = PatientMemoryStore(memory["records"])

    if not cases:
        raise ValueError("No benchmark cases")

    observed = set()

    for case in cases:
        identity = visit_identity(case)
        key = visit_key(identity)

        if key in observed:
            raise ValueError(f"Duplicate visit: {key}")
        observed.add(key)

        if key not in annotations:
            raise ValueError(f"Missing annotation: {key}")

        annotation = annotations[key]

        if "relevant_memory_ids" not in annotation:
            raise ValueError(f"Missing relevance label: {key}")

        gold = annotation["relevant_memory_ids"]

        if len(gold) != len(set(gold)):
            raise ValueError(f"Duplicate gold IDs: {key}")

        eligible = store.retrieve(
            identity,
            query="",
            mode="full_history",
        )

        eligible_ids = {
            row["memory_id"]
            for row in eligible["records"]
        }

        invalid = set(gold) - eligible_ids

        if invalid:
            raise ValueError(
                f"Invalid gold memory IDs for {key}: "
                f"{sorted(invalid)}"
            )

    if observed != set(annotations):
        raise ValueError(
            "Annotation and case coverage mismatch"
        )

    return {
        "status": "PASS",
        "validated_cases": len(cases),
    }
