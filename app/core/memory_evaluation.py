"""Retrospective memory metrics.

Annotations never enter model observations.

Memory citations are validated against the memory context that was visible
at the exact decision step where the citation was produced.

This matters for dynamic longitudinal retrieval because the retrieved
Top-K memory set may change after new clinical evidence becomes available.
"""

from copy import deepcopy


def visit_key(identity):
    import json

    return json.dumps(
        [identity["patient_id"], identity["visit_id"]],
        ensure_ascii=False,
    )


def ratio(numerator, denominator, missing=False):
    return {
        "value": (
            None
            if missing or not denominator
            else numerator / denominator
        ),
        "numerator": None if missing else numerator,
        "denominator": None if missing else denominator,
        "status": (
            "missing_annotation"
            if missing
            else "available"
            if denominator
            else "not_applicable"
        ),
    }


def validate_annotations(annotations):
    if not isinstance(annotations, dict):
        raise ValueError(
            "Memory annotations must map visit keys to labels"
        )

    for key, row in annotations.items():
        if (
            not isinstance(key, str)
            or not isinstance(row, dict)
            or set(row)
            - {
                "relevant_memory_ids",
                "stale_memory_ids",
                "misused_memory_ids",
            }
        ):
            raise ValueError(
                "Invalid memory annotation fields"
            )

        for values in row.values():
            if (
                not isinstance(values, list)
                or any(
                    not isinstance(x, str) or not x
                    for x in values
                )
                or len(values) != len(set(values))
            ):
                raise ValueError(
                    "Memory annotation IDs must be unique "
                    "nonempty strings"
                )

        if (
            "misused_memory_ids" in row
            and not set(
                row["misused_memory_ids"]
            )
            <= set(
                row.get("stale_memory_ids", [])
            )
        ):
            raise ValueError(
                "Misused stale memories must be a subset "
                "of stale_memory_ids"
            )


def _memory_ids_from_context(context):
    """Return the memory IDs visible in one memory context."""

    if not isinstance(context, dict):
        return set()

    records = context.get("records", [])

    if not isinstance(records, list):
        return set()

    result = set()

    for record in records:
        if not isinstance(record, dict):
            continue

        memory_id = record.get("memory_id")

        if isinstance(memory_id, str) and memory_id:
            result.add(memory_id)

    return result


def _citation_audit(audit, final_selected):
    """Validate citations using each decision's own memory context.

    A dynamic retrieval experiment can expose different Top-K memories
    at different decision steps. Therefore, citations must not be checked
    only against the final runtime memory context.

    Returns:
        {
            "cited_ids": set(...),
            "invalid_model_ids": set(...),
            "steps": [...]
        }

    Raises:
        ValueError:
            Only when an ID recorded as a valid citation was not actually
            present in the memory context visible at that decision step.
            This indicates an internal grounding/audit inconsistency.
    """

    cited_ids = set()
    invalid_model_ids = set()
    steps = []

    for step_index, row in enumerate(audit):
        if not isinstance(row, dict):
            continue

        if row.get("status") != "success":
            continue

        citation = row.get(
            "memory_citations",
            {},
        )

        if not isinstance(citation, dict):
            continue

        raw_ids = citation.get("ids", [])

        if not isinstance(raw_ids, list):
            raw_ids = []

        valid_ids = {
            value
            for value in raw_ids
            if isinstance(value, str) and value
        }

        raw_invalid_ids = citation.get(
            "invalid_ids",
            [],
        )

        if not isinstance(raw_invalid_ids, list):
            raw_invalid_ids = []

        model_invalid_ids = {
            value
            for value in raw_invalid_ids
            if isinstance(value, str) and value
        }

        # HospitalLLMPolicy stores the memory context that was visible
        # for every encounter decision.
        step_context = row.get("memory_context")

        if isinstance(step_context, dict):
            provided_ids = _memory_ids_from_context(
                step_context
            )
            validation_source = "decision_memory_context"
        else:
            # Backward compatibility for older audit rows that were
            # created before per-decision memory_context was stored.
            provided_ids = set(final_selected)
            validation_source = "final_memory_context_fallback"

        outside = valid_ids - provided_ids

        if outside:
            raise ValueError(
                "Citation outside memory visible at decision step "
                f"{step_index}: {sorted(outside)}"
            )

        cited_ids.update(valid_ids)
        invalid_model_ids.update(model_invalid_ids)

        steps.append(
            {
                "step_index": step_index,
                "role": row.get("role"),
                "provided_memory_ids": sorted(
                    provided_ids
                ),
                "cited_ids": sorted(
                    valid_ids
                ),
                "invalid_model_ids": sorted(
                    model_invalid_ids
                ),
                "validation_source": validation_source,
                "reported": citation.get(
                    "reported",
                    False,
                ),
                "valid": (
                    not outside
                    and not model_invalid_ids
                ),
            }
        )

    return {
        "cited_ids": cited_ids,
        "invalid_model_ids": invalid_model_ids,
        "steps": steps,
    }


def evaluate_memory(
    context,
    audit,
    annotation=None,
    eligible_ids=None,
):
    annotation = annotation or {}

    validate_annotations(
        {
            "visit": annotation,
        }
    )

    if eligible_ids is not None:
        eligible_set = set(eligible_ids)

        for field in (
            "relevant_memory_ids",
            "stale_memory_ids",
        ):
            if not set(
                annotation.get(field, [])
            ) <= eligible_set:
                raise ValueError(
                    "Annotations reference unavailable, "
                    "future or other-patient memory"
                )

    # This is the final retrieved memory set.
    #
    # It is used for retrieval metrics such as Precision / Recall.
    # It must NOT be used as the sole citation validation source
    # because retrieved Top-K can change during the visit.
    selected = _memory_ids_from_context(
        context
    )

    relevant = set(
        annotation.get(
            "relevant_memory_ids",
            [],
        )
    )

    stale = set(
        annotation.get(
            "stale_memory_ids",
            [],
        )
    )

    citation_result = _citation_audit(
        audit,
        selected,
    )

    cited = citation_result["cited_ids"]

    invalid_model_ids = citation_result[
        "invalid_model_ids"
    ]

    # Misuse requires external review.
    #
    # Citing historical information alone does not prove that
    # the model treated it as a current fact.
    misused = set(
        annotation.get(
            "misused_memory_ids",
            [],
        )
    )

    if not misused <= selected:
        raise ValueError(
            "Misuse annotation references memory "
            "not shown in this run"
        )

    successful_non_patient_audits = [
        row
        for row in audit
        if isinstance(row, dict)
        and row.get("status") == "success"
        and row.get("role") != "patient"
    ]

    citation_reporting_complete = all(
        isinstance(
            row.get("memory_citations"),
            dict,
        )
        and row.get(
            "memory_citations",
            {},
        ).get(
            "reported",
            False,
        )
        for row in successful_non_patient_audits
    )

    if invalid_model_ids:
        citation_validation_status = (
            "invalid_model_citation_reported"
        )
    else:
        citation_validation_status = "valid"

    return {
        "precision": ratio(
            len(selected & relevant),
            len(selected),
            "relevant_memory_ids"
            not in annotation,
        ),
        "recall": ratio(
            len(selected & relevant),
            len(relevant),
            "relevant_memory_ids"
            not in annotation,
        ),
        "stale_retrieval_rate": ratio(
            len(selected & stale),
            len(selected),
            "stale_memory_ids"
            not in annotation,
        ),
        "stale_misuse_rate": ratio(
            len(misused),
            len(selected & stale),
            "misused_memory_ids"
            not in annotation,
        ),

        # Final retrieval state
        "retrieved_ids": sorted(
            selected
        ),

        # Citations accumulated across all decision steps
        "cited_ids": sorted(
            cited
        ),

        # IDs proposed by the model but rejected/sanitized by
        # HospitalLLMPolicy because they were not valid provided IDs.
        "invalid_model_citation_ids": sorted(
            invalid_model_ids
        ),

        "citation_validation_status": (
            citation_validation_status
        ),

        # Step-level evidence for longitudinal / dynamic retrieval.
        "citation_steps": deepcopy(
            citation_result["steps"]
        ),

        "citation_reporting_complete": (
            citation_reporting_complete
        ),

        "interpretation": (
            "Citations are validated against the memory context "
            "visible at each decision step. Retrieved-memory metrics "
            "refer to the final retrieval state. Model-proposed invalid "
            "IDs are recorded separately and do not become valid citations. "
            "Semantic use and clinical correctness still require review."
        ),
    }


def compare_memory_benefit(
    baseline,
    candidate,
    expected_diagnoses,
):
    """Paired observed accuracy difference.

    This is not a causal or significance test.
    """

    if (
        baseline.get("mode") != "none"
        or candidate.get("mode") == "none"
    ):
        raise ValueError(
            "Compare a no-memory baseline "
            "with a memory condition"
        )

    signature = baseline.get(
        "experiment_signature"
    )

    if (
        not signature
        or signature
        != candidate.get(
            "experiment_signature"
        )
    ):
        raise ValueError(
            "Cases, initial memory and non-memory "
            "experimental settings must match"
        )

    left = {
        visit_key(v["identity"]): v
        for v in baseline["visits"]
    }

    right = {
        visit_key(v["identity"]): v
        for v in candidate["visits"]
    }

    if left.keys() != right.keys():
        raise ValueError(
            "Paired visits must match"
        )

    normalize = lambda s: " ".join(
        s.casefold().split()
    )

    included = []
    excluded = []

    for key, visit in left.items():
        labels = expected_diagnoses.get(
            key
        )

        if labels is None:
            excluded.append(
                {
                    "visit": key,
                    "reason": (
                        "missing_diagnosis_labels"
                    ),
                }
            )
            continue

        if (
            not isinstance(labels, list)
            or not labels
            or any(
                not isinstance(s, str)
                or not s.strip()
                for s in labels
            )
        ):
            raise ValueError(
                "Expected diagnoses require "
                "explicit nonempty accepted labels"
            )

        runtimes = [
            list(
                v["final_state"][
                    "cases"
                ].values()
            )
            for v in (
                visit,
                right[key],
            )
        ]

        if any(
            len(rows) != 1
            for rows in runtimes
        ):
            raise ValueError(
                "Memory comparison requires "
                "single-visit states"
            )

        states = [
            rows[0]
            for rows in runtimes
        ]

        if not all(
            state["is_completed"]
            for state in states
        ):
            excluded.append(
                {
                    "visit": key,
                    "reason": (
                        "incomplete_visit"
                    ),
                }
            )
            continue

        accepted = {
            normalize(label)
            for label in labels
        }

        scores = [
            int(
                "diagnosis_unresolved"
                not in state["alerts"]
                and normalize(
                    state[
                        "assessment_summary"
                    ]
                )
                in accepted
            )
            for state in states
        ]

        included.append(
            {
                "visit": key,
                "baseline_correct": (
                    scores[0]
                ),
                "candidate_correct": (
                    scores[1]
                ),
                "difference": (
                    scores[1]
                    - scores[0]
                ),
            }
        )

    observed = (
        sum(
            row["difference"]
            for row in included
        )
        / len(included)
        if included
        else None
    )

    return {
        "memory_benefit": (
            observed
            if not excluded
            else None
        ),
        "observed_subset_benefit": (
            observed
        ),
        "included": included,
        "excluded": excluded,
        "status": (
            "missing_or_censored"
            if excluded
            else "available"
            if included
            else "not_applicable"
        ),
        "interpretation": (
            "Closed-loop differences may include changed prior decisions; "
            "use fixed memory to isolate retrieval conditions."
        ),
    }