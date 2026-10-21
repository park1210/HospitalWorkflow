
"""Shared initial query builder for memory benchmark experiments.

Only initially visible clinical information is used.
"""

from app.core.clinical_observation import (
    prepare_encounter,
    memory_query,
    initial_symptoms,
)


def prepare_memory_case(source):
    """Normalize a case using the existing encounter preparation."""
    return prepare_encounter(source)


def build_initial_memory_query(source, *, prepared=False):
    """Build the query shared by embedding and evaluation.

    Gold diagnoses and future examination results must not
    be used to construct the memory retrieval query.
    """
    case = source if prepared else prepare_memory_case(source)

    visible = case.get("doctor_visible_info", {})

    chief_complaint = str(
        visible.get("chief_complaint", "")
    )

    # Preserve existing behavior for legacy cases.
    if "index_encounter_id" not in case:
        return chief_complaint

    return memory_query({
        "chief_complaint": chief_complaint,
        "current_symptoms": initial_symptoms(case),
        "vital_signs": visible.get("initial_vitals", {}),
    })
