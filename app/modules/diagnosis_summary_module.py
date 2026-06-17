from __future__ import annotations

from app.utils.department_catalog import (
    choose_department_from_scores,
    combine_department_scores,
    infer_department_scores_by_source,
    normalize_department,
)


class DiagnosisSummaryModule:
    def build(self, state: dict, transcript: list[dict[str, str]]) -> dict[str, object]:
        objective_findings = [str(item).strip() for item in state.get("objective_findings", []) if str(item).strip()]
        consults = [item for item in state.get("consultation_history", []) if isinstance(item, dict)]
        suspected = [str(item).strip() for item in state.get("suspected_diagnoses", []) if str(item).strip()]
        working_diagnosis = str(state.get("er_working_diagnosis", "")).strip()
        evidence_scores = infer_department_scores_by_source(
            {
                "working_diagnosis": working_diagnosis,
                "objective_findings": objective_findings,
                "consult_opinions": [str(item.get("opinion", "")).strip() for item in consults if str(item.get("opinion", "")).strip()],
                "working_problem_list": [str(item).strip() for item in state.get("working_problem_list", []) if str(item).strip()],
            },
            prefer_clinical_department=True,
        )
        combined_scores = combine_department_scores(
            evidence_scores,
            {str(k).strip(): float(v) for k, v in (state.get("department_routing_scores", {}) or {}).items() if str(k).strip()},
        )
        responsible_department = normalize_department(
            choose_department_from_scores(
                combined_scores,
                default=str(state.get("responsible_department", "")).strip() or "general_medicine",
                fallback_if_ambiguous="internal_medicine",
                ambiguity_margin=1.5,
                low_confidence_threshold=1.5,
            ),
            default="general_medicine",
        )
        return {
            "working_diagnosis": working_diagnosis,
            "responsible_department": responsible_department,
            "diagnostic_service": str(state.get("diagnostic_service", "")).strip() or responsible_department,
            "suspected_diagnoses": suspected,
            "objective_findings": objective_findings,
            "specialty_consults": consults,
            "ipass_handoff": state.get("ipass_handoff", {}) or {},
            "department_routing_scores": state.get("department_routing_scores", {}) or {},
            "confidence": float(state.get("er_confidence", 0.0) or 0.0),
        }
