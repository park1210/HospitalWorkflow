from __future__ import annotations

from typing import Any

from app.config import settings
from app.utils.department_catalog import infer_department_scores, normalize_department
from app.utils.diagnosis_catalog import extract_known_diagnoses


GENERIC_DIAGNOSIS_PREFIXES = (
    "possible ",
    "undifferentiated",
    "acute abdominal",
    "acute ",
)


class DiagnosticReflectionModule:
    def _is_specific_diagnosis(self, diagnosis: str) -> bool:
        normalized = str(diagnosis).strip().lower()
        if not normalized:
            return False
        return not any(normalized.startswith(prefix) for prefix in GENERIC_DIAGNOSIS_PREFIXES)

    def _best_objective_diagnosis(self, state: dict[str, Any]) -> str:
        objective_text = "\n".join(
            str(item).strip()
            for item in state.get("objective_findings", [])
            if str(item).strip()
        )
        if not objective_text:
            return ""
        extracted = extract_known_diagnoses(objective_text, limit=1)
        return extracted[0] if extracted else ""

    def _best_consult_diagnosis(self, state: dict[str, Any]) -> str:
        consult_text = "\n".join(
            str(item.get("opinion", "")).strip()
            for item in state.get("consultation_history", [])
            if isinstance(item, dict) and str(item.get("opinion", "")).strip()
        )
        if not consult_text:
            return ""
        extracted = extract_known_diagnoses(consult_text, limit=1)
        return extracted[0] if extracted else ""

    def _supported_department(self, state: dict[str, Any]) -> tuple[str, int, int]:
        evidence = [
            str(state.get("er_working_diagnosis", "")).strip(),
            str(state.get("final_diagnosis", "")).strip(),
            *(str(item).strip() for item in state.get("objective_findings", []) if str(item).strip()),
            *(str(item.get("opinion", "")).strip() for item in state.get("consultation_history", []) if isinstance(item, dict)),
            *(str(item).strip() for item in state.get("working_problem_list", []) if str(item).strip()),
        ]
        scores = infer_department_scores(evidence, prefer_clinical_department=True)
        if not scores:
            return "", 0, 0
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        top_department, top_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0
        margin = top_score - second_score
        if top_score < settings.STRUCTURED_REFLECTION_MIN_DEPARTMENT_SCORE:
            return "", top_score, margin
        if margin < settings.STRUCTURED_REFLECTION_MIN_DEPARTMENT_MARGIN:
            return "", top_score, margin
        return normalize_department(top_department, default="general_medicine"), top_score, margin

    def _apply_conservative_updates(self, state: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        updates: dict[str, Any] = {}
        triggers: list[str] = []

        current_working = str(state.get("er_working_diagnosis", "")).strip()
        current_department = normalize_department(
            str(state.get("responsible_department", "")).strip() or "general_medicine",
            default="general_medicine",
        )
        current_service = str(state.get("diagnostic_service", "")).strip() or current_department

        objective_diagnosis = self._best_objective_diagnosis(state)
        if objective_diagnosis and objective_diagnosis != current_working:
            if not self._is_specific_diagnosis(current_working) or current_working == "undifferentiated acute complaint":
                updates["er_working_diagnosis"] = objective_diagnosis
                triggers.append("objective_exact_diagnosis")

        if "er_working_diagnosis" not in updates:
            consult_diagnosis = self._best_consult_diagnosis(state)
            if consult_diagnosis and consult_diagnosis != current_working:
                if not self._is_specific_diagnosis(current_working):
                    updates["er_working_diagnosis"] = consult_diagnosis
                    triggers.append("consult_exact_diagnosis")

        supported_department, top_score, margin = self._supported_department(state | updates)
        if supported_department and supported_department != current_department:
            if current_department in {"general_medicine", "radiology"}:
                updates["responsible_department"] = supported_department
                triggers.append(f"department_evidence_alignment(score={top_score},margin={margin})")

        updated_department = normalize_department(
            str(updates.get("responsible_department", current_department)).strip() or "general_medicine",
            default="general_medicine",
        )
        if supported_department and current_service in {"general_medicine", "radiology", "internal_medicine"}:
            if updated_department == supported_department:
                updates["diagnostic_service"] = supported_department
                triggers.append("service_alignment")

        return updates, triggers

    def review(self, phase: str, state: dict[str, Any]) -> dict[str, Any]:
        if not settings.USE_STRUCTURED_REFLECTION:
            return {
                "phase": phase,
                "applied": False,
                "updates": {},
                "triggers": [],
                "rationale": "Structured reflection is disabled.",
            }

        updates, triggers = self._apply_conservative_updates(state)
        applied = bool(updates)
        if applied:
            rationale = (
                f"Structured reflection ({phase}) applied a conservative correction because stronger evidence "
                f"supported {', '.join(triggers)}."
            )
        else:
            rationale = (
                f"Structured reflection ({phase}) found no high-signal contradiction that justified overriding the current workflow state."
            )
        return {
            "phase": phase,
            "applied": applied,
            "updates": updates,
            "triggers": triggers,
            "rationale": rationale,
        }
