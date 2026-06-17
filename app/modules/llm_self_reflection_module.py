from __future__ import annotations

import json
from typing import Any

from app.config import settings
from app.llm.ollama_client import OllamaClient
from app.utils.department_catalog import infer_department_scores, normalize_department
from app.utils.diagnosis_catalog import extract_known_diagnoses, match_known_diagnosis
from app.utils.prompt_loader import load_prompt

GENERIC_DIAGNOSIS_PREFIXES = (
    "possible ",
    "undifferentiated",
    "acute abdominal",
    "acute ",
)


class LLMSelfReflectionModule:
    def __init__(self) -> None:
        self.client = OllamaClient()
        self.system_prompt = load_prompt("diagnostic_self_reflection_system.txt")
        if not self.system_prompt:
            raise ValueError(
                "Prompt file prompts/diagnostic_self_reflection_system.txt is required for LLM self-reflection."
            )

    def _is_specific_diagnosis(self, diagnosis: str) -> bool:
        normalized = str(diagnosis).strip().lower()
        if not normalized:
            return False
        return not any(normalized.startswith(prefix) for prefix in GENERIC_DIAGNOSIS_PREFIXES)

    def _objective_exact_diagnosis(self, state: dict[str, Any]) -> str:
        evidence_text = "\n".join(
            str(item).strip() for item in state.get("objective_findings", []) if str(item).strip()
        )
        if not evidence_text:
            return ""
        extracted = extract_known_diagnoses(evidence_text, limit=1)
        return extracted[0] if extracted else ""

    def _consult_exact_diagnosis(self, state: dict[str, Any]) -> str:
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
        return normalize_department(top_department, default="general_medicine"), top_score, margin

    def _should_reflect(self, state: dict[str, Any]) -> tuple[bool, list[str]]:
        if not settings.USE_LLM_SELF_REFLECTION:
            return False, []
        if int(state.get("llm_self_reflection_count", 0) or 0) >= settings.LLM_SELF_REFLECTION_MAX_PER_CASE:
            return False, []

        triggers: list[str] = []
        current_working = str(state.get("er_working_diagnosis", "")).strip()
        current_department = normalize_department(
            str(state.get("responsible_department", "")).strip() or "general_medicine",
            default="general_medicine",
        )
        current_service = str(state.get("diagnostic_service", "")).strip() or current_department

        objective_exact = self._objective_exact_diagnosis(state)
        consult_exact = self._consult_exact_diagnosis(state)
        supported_department, top_score, margin = self._supported_department(state)

        if objective_exact and not self._is_specific_diagnosis(current_working):
            triggers.append("generic_diagnosis_with_objective_exact")
        if consult_exact and not self._is_specific_diagnosis(current_working):
            triggers.append("generic_diagnosis_with_consult_exact")
        if (
            supported_department
            and supported_department not in {"general_medicine", "radiology", "internal_medicine"}
            and current_department in {"general_medicine", "radiology", "internal_medicine"}
            and top_score >= settings.STRUCTURED_REFLECTION_MIN_DEPARTMENT_SCORE
            and margin >= settings.STRUCTURED_REFLECTION_MIN_DEPARTMENT_MARGIN
        ):
            triggers.append("stale_department_against_strong_evidence")
        if current_service != current_department and current_department != "general_medicine":
            triggers.append("service_department_mismatch")

        return bool(triggers), triggers

    def _validate_override(
        self,
        state: dict[str, Any],
        proposed_diagnosis: str,
        proposed_department: str,
    ) -> tuple[bool, dict[str, Any], list[str]]:
        updates: dict[str, Any] = {}
        triggers: list[str] = []

        current_working = str(state.get("er_working_diagnosis", "")).strip()
        current_department = normalize_department(
            str(state.get("responsible_department", "")).strip() or "general_medicine",
            default="general_medicine",
        )
        current_service = str(state.get("diagnostic_service", "")).strip() or current_department
        objective_exact = self._objective_exact_diagnosis(state)
        consult_exact = self._consult_exact_diagnosis(state)
        supported_department, top_score, margin = self._supported_department(state)

        normalized_department = normalize_department(proposed_department, default=current_department)
        matched_proposed = match_known_diagnosis(proposed_diagnosis) if proposed_diagnosis else None

        if objective_exact and matched_proposed:
            if match_known_diagnosis(objective_exact) == matched_proposed and not self._is_specific_diagnosis(current_working):
                updates["er_working_diagnosis"] = objective_exact
                triggers.append("llm_confirmed_objective_exact")
        elif consult_exact and matched_proposed:
            if match_known_diagnosis(consult_exact) == matched_proposed and not self._is_specific_diagnosis(current_working):
                updates["er_working_diagnosis"] = consult_exact
                triggers.append("llm_confirmed_consult_exact")

        if (
            supported_department
            and normalized_department == supported_department
            and current_department in {"general_medicine", "radiology", "internal_medicine"}
            and top_score >= settings.STRUCTURED_REFLECTION_MIN_DEPARTMENT_SCORE
            and margin >= settings.STRUCTURED_REFLECTION_MIN_DEPARTMENT_MARGIN
        ):
            updates["responsible_department"] = supported_department
            triggers.append("llm_confirmed_department_alignment")
            if current_service in {"general_medicine", "radiology", "internal_medicine"}:
                updates["diagnostic_service"] = supported_department
                triggers.append("llm_confirmed_service_alignment")

        return bool(updates), updates, triggers

    def review(self, phase: str, state: dict[str, Any], transcript: list[dict[str, str]]) -> dict[str, Any]:
        should_reflect, trigger_reasons = self._should_reflect(state)
        if not should_reflect:
            return {
                "phase": phase,
                "used_llm": False,
                "applied": False,
                "updates": {},
                "triggers": [],
                "rationale": f"LLM self-reflection ({phase}) did not activate because no high-risk ambiguity trigger was present.",
            }

        payload = {
            "phase": phase,
            "current_working_diagnosis": str(state.get("er_working_diagnosis", "")).strip(),
            "current_department": str(state.get("responsible_department", "")).strip(),
            "current_service": str(state.get("diagnostic_service", "")).strip(),
            "working_problem_list": list(state.get("working_problem_list", []))[:4],
            "objective_findings": list(state.get("objective_findings", []))[-5:],
            "specialty_consults": list(state.get("consultation_history", []))[-4:],
            "known_information": list(state.get("known_information", []))[-6:],
            "trigger_reasons": trigger_reasons,
            "instruction": (
                "Decide whether the current diagnosis or department should be conservatively corrected. "
                "Only propose a diagnosis if it is directly supported by the evidence already shown."
            ),
        }

        try:
            response = self.client.chat(
                self.system_prompt,
                json.dumps(payload, ensure_ascii=False, indent=2),
            ).strip()
            parsed = json.loads(response)
        except Exception:
            return {
                "phase": phase,
                "used_llm": True,
                "applied": False,
                "updates": {},
                "triggers": trigger_reasons,
                "rationale": f"LLM self-reflection ({phase}) triggered but produced no valid structured output.",
            }

        should_override = bool(parsed.get("should_override"))
        proposed_diagnosis = str(parsed.get("proposed_diagnosis", "")).strip()
        proposed_department = str(parsed.get("proposed_department", "")).strip()
        rationale = str(parsed.get("rationale", "")).strip()

        if not should_override:
            return {
                "phase": phase,
                "used_llm": True,
                "applied": False,
                "updates": {},
                "triggers": trigger_reasons,
                "rationale": rationale or f"LLM self-reflection ({phase}) reviewed the case and kept the current state.",
            }

        valid, updates, validated_triggers = self._validate_override(state, proposed_diagnosis, proposed_department)
        if not valid:
            return {
                "phase": phase,
                "used_llm": True,
                "applied": False,
                "updates": {},
                "triggers": trigger_reasons,
                "rationale": (
                    rationale
                    or f"LLM self-reflection ({phase}) proposed a change, but the change was rejected because it was not strongly supported by current evidence."
                ),
            }

        return {
            "phase": phase,
            "used_llm": True,
            "applied": True,
            "updates": updates,
            "triggers": validated_triggers,
            "rationale": (
                rationale
                or f"LLM self-reflection ({phase}) applied a conservative evidence-supported correction."
            ),
        }
