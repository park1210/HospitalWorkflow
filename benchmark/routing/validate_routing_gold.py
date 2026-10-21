
"""Validate independently reviewed Routing Benchmark gold labels."""

from app.utils.department_catalog import SUPPORTED_DEPARTMENTS


VALID_SPLITS = {"train", "validation", "test"}
VALID_REVIEW_STATUSES = {"reviewed", "pending", "rejected"}


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def validate_routing_gold(cases, *, require_reviewed=True):
    """Validate case IDs, patient split, observations and gold labels.

    Returns a validation report. Does not infer gold specialties.
    """
    if not isinstance(cases, list) or not cases:
        raise ValueError("Nonempty routing cases list required")

    supported = set(SUPPORTED_DEPARTMENTS)
    case_ids = set()
    patient_splits = {}
    status_counts = {
        status: 0 for status in VALID_REVIEW_STATUSES
    }

    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Case must be an object")

        case_id = case.get("case_id")
        patient_id = case.get("patient_id")
        split = case.get("split")

        if not _nonempty(case_id) or not _nonempty(patient_id):
            raise ValueError("Case and patient IDs required")

        if case_id in case_ids:
            raise ValueError(f"Duplicate case ID: {case_id}")
        case_ids.add(case_id)

        if split not in VALID_SPLITS:
            raise ValueError(f"Invalid split: {case_id}")

        previous = patient_splits.setdefault(patient_id, split)
        if previous != split:
            raise ValueError(
                f"Patient crosses data splits: {patient_id}"
            )

        observation = case.get("observation")
        if not isinstance(observation, dict):
            raise ValueError(
                f"Observation must be an object: {case_id}"
            )

        if not any(
            observation.get(field)
            for field in (
                "chief_complaint",
                "current_symptoms",
                "objective_findings",
                "history",
                "vital_signs",
            )
        ):
            raise ValueError(
                f"No observable current information: {case_id}"
            )

        candidates = case.get("candidate_departments")

        if (
            not isinstance(candidates, list)
            or not candidates
            or any(not _nonempty(d) for d in candidates)
            or len(set(candidates)) != len(candidates)
            or not set(candidates) <= supported
        ):
            raise ValueError(
                f"Invalid candidate departments: {case_id}"
            )

        gold = case.get("gold")
        if not isinstance(gold, dict):
            raise ValueError(f"Missing gold: {case_id}")

        status = gold.get("review_status")
        if status not in VALID_REVIEW_STATUSES:
            raise ValueError(
                f"Invalid review status: {case_id}"
            )

        status_counts[status] += 1

        if require_reviewed and status != "reviewed":
            raise ValueError(
                f"Gold not reviewed: {case_id}"
            )

        if status != "reviewed":
            continue

        reference = gold.get("review_reference")
        if not _nonempty(reference):
            raise ValueError(
                f"Missing review reference: {case_id}"
            )

        acceptable = gold.get("acceptable_specialties")
        if (
            not isinstance(acceptable, list)
            or not acceptable
            or len(set(acceptable)) != len(acceptable)
            or not set(acceptable) <= set(candidates)
        ):
            raise ValueError(
                f"Invalid acceptable specialties: {case_id}"
            )

        primary = gold.get("primary_specialty")
        if primary is not None and primary not in acceptable:
            raise ValueError(
                f"Primary specialty not acceptable: {case_id}"
            )

    return {
        "status": "PASS",
        "case_count": len(cases),
        "patient_count": len(patient_splits),
        "review_status_counts": status_counts,
        "reviewed_count": status_counts["reviewed"],
    }
