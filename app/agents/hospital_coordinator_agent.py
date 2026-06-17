from __future__ import annotations

from app.utils.department_catalog import (
    build_department_candidates,
    choose_department_from_scores,
    combine_department_scores,
    get_curated_department_assignment,
    infer_department_scores_from_catalog,
    infer_department_scores_by_source,
    normalize_department,
    prefer_specific_department,
)


class HospitalCoordinatorAgent:
    DIRECT_DIAGNOSTIC_DEPARTMENTS = {
        "general_medicine",
        "surgery",
        "neurology",
        "cardiology",
        "pulmonology",
        "gastroenterology",
        "nephrology",
        "hematology",
        "infectious_disease",
        "obstetrics_gynecology",
        "psychiatry",
        "orthopedics",
        "urology",
    }

    INTERNAL_MEDICINE_UMBRELLA_DEPARTMENTS = {
        "internal_medicine",
        "endocrinology",
        "rheumatology",
        "pediatrics",
        "dermatology",
        "ophthalmology",
        "otolaryngology",
    }

    def assign_entry_department(self, case: dict) -> dict[str, str]:
        return {
            "entry_department": "er",
            "rationale": "All undifferentiated acute patients enter the diagnosis workflow through ER first.",
        }

    def choose_diagnostic_service(self, state: dict) -> dict[str, str]:
        exact_diagnosis = str(state.get("er_working_diagnosis", "")).strip() or str(state.get("final_diagnosis", "")).strip()
        exact_assignment = get_curated_department_assignment(exact_diagnosis)
        if exact_assignment and exact_diagnosis and not exact_diagnosis.lower().startswith("possible "):
            department = normalize_department(str(exact_assignment.get("department", "")).strip(), default="general_medicine")
            return {
                "diagnostic_service": department,
                "responsible_department": department,
                "rationale": f"The ER already has a specific diagnosis that maps to {department}, so the coordinator aligns routing to the curated owning department.",
            }

        explicit_service = str(state.get("diagnostic_service", "")).strip()
        explicit_department = str(state.get("responsible_department", "")).strip()
        ipass_handoff = state.get("ipass_handoff", {}) or {}
        if explicit_service and explicit_department and isinstance(ipass_handoff, dict) and ipass_handoff:
            return {
                "diagnostic_service": explicit_service,
                "responsible_department": explicit_department,
                "rationale": f"The ER already prepared a structured handoff to {explicit_department}, so the coordinator preserves that routing.",
            }

        fallback_department = str(state.get("responsible_department", "")).strip() or "general_medicine"
        evidence_scores = infer_department_scores_by_source(
            {
                "supported_diagnosis": str(state.get("final_diagnosis", "")).strip(),
                "working_diagnosis": str(state.get("er_working_diagnosis", "")).strip(),
                "objective_findings": [str(item).strip() for item in state.get("objective_findings", []) if str(item).strip()],
                "consult_opinions": [
                    str(item.get("opinion", "")).strip()
                    for item in state.get("consultation_history", [])
                    if isinstance(item, dict) and str(item.get("opinion", "")).strip()
                ],
                "working_problem_list": [str(item).strip() for item in state.get("working_problem_list", []) if str(item).strip()],
            },
            prefer_clinical_department=True,
        )
        catalog_query = " ".join(
            [
                str(state.get("er_working_diagnosis", "")).strip(),
                " ".join(str(item).strip() for item in state.get("objective_findings", []) if str(item).strip()),
                " ".join(str(item).strip() for item in state.get("known_information", [])[-3:] if str(item).strip()),
            ]
        ).strip()
        catalog_scores = infer_department_scores_from_catalog(catalog_query, limit=6, min_score=0.34)
        combined_scores = combine_department_scores(
            evidence_scores,
            catalog_scores,
            {str(k).strip(): float(v) for k, v in (state.get("department_routing_scores", {}) or {}).items() if str(k).strip()},
            {str(k).strip(): float(v) for k, v in (state.get("candidate_scores", {}) or {}).items() if str(k).strip()},
        )
        department = normalize_department(
            prefer_specific_department(
                combined_scores,
                choose_department_from_scores(
                    combined_scores,
                    default=fallback_department,
                    fallback_if_ambiguous="internal_medicine",
                    ambiguity_margin=1.5,
                    low_confidence_threshold=1.5,
                ),
            ),
            default="general_medicine",
        )

        if department in self.DIRECT_DIAGNOSTIC_DEPARTMENTS:
            return {
                "diagnostic_service": department,
                "responsible_department": department,
                "rationale": f"The ER concluded the dominant diagnostic refinement should come from {department}.",
            }

        if department in self.INTERNAL_MEDICINE_UMBRELLA_DEPARTMENTS:
            return {
                "diagnostic_service": "internal_medicine",
                "responsible_department": department,
                "rationale": "The ER completed its initial workup and routed the case through the internal-medicine diagnostic umbrella.",
            }

        routing_candidates = build_department_candidates(combined_scores, limit=2)
        return {
            "diagnostic_service": "general_medicine",
            "responsible_department": department if department else "general_medicine",
            "rationale": f"The ER completed its initial diagnostic workup and defaulted to general medical diagnostic refinement after considering shortlist candidates {routing_candidates}.",
        }

    def finalize_route(self, state: dict) -> dict[str, str]:
        responsible_department = str(state.get("responsible_department", "")).strip() or "general_medicine"
        return {
            "destination": "diagnosis_complete",
            "responsible_department": responsible_department,
            "handoff_summary": str(state.get("latest_rationale", "")).strip(),
        }
