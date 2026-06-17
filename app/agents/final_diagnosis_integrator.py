from __future__ import annotations

import json

from app.config import settings
from app.llm.ollama_client import OllamaClient
from app.utils.department_catalog import infer_department_from_texts, normalize_department
from app.utils.diagnosis_catalog import extract_known_diagnoses, match_known_diagnosis
from app.utils.prompt_loader import load_prompt


DEFAULT_FINAL_DIAGNOSIS_INTEGRATOR_PROMPT = """
You are the final diagnosis integrator in a hospital diagnostic workflow simulation.

Your role:
- combine ER findings, specialty refinement, and objective evidence
- produce the most supported final diagnosis
- keep the final department aligned with the strongest diagnostic evidence

Rules:
- prefer objective findings over vague impressions
- do not overstate certainty when evidence is weak
- if a specific diagnosis is directly supported, use it
- keep the explanation concise and evidence-based
"""


GENERIC_DIAGNOSIS_PREFIXES = (
    "possible ",
    "undifferentiated",
    "acute abdominal",
    "possible acute",
    "possible central",
    "possible multisystem",
    "possible systemic",
    "possible infectious",
    "possible pulmonary",
    "possible cardiac",
    "possible urinary",
    "possible gynecologic",
    "possible bowel",
    "possible structural",
    "possible cerebellar",
    "possible neuromuscular junction",
    "possible neurologic process",
)


class FinalDiagnosisIntegrator:
    def __init__(self) -> None:
        self.client = OllamaClient()
        self.system_prompt = load_prompt(
            "final_diagnosis_integrator_system.txt",
            DEFAULT_FINAL_DIAGNOSIS_INTEGRATOR_PROMPT,
        )

    def _is_specific_diagnosis(self, diagnosis: str) -> bool:
        normalized = str(diagnosis).strip().lower()
        if not normalized:
            return False
        return not any(normalized.startswith(prefix) for prefix in GENERIC_DIAGNOSIS_PREFIXES)

    def _extract_supported_diagnosis(self, texts: list[str]) -> str:
        cleaned = [str(item).strip() for item in texts if str(item).strip()]
        if not cleaned:
            return ""

        extracted = extract_known_diagnoses("\n".join(cleaned), limit=1)
        if extracted:
            return extracted[0]

        for text in cleaned:
            matched = match_known_diagnosis(text)
            if matched:
                return matched

        return ""

    def _resolve_department(
        self,
        working: str,
        objective_findings: list[str],
        consults: list[dict[str, object]],
        default_department: str,
        diagnostic_service: str,
    ) -> tuple[str, str]:
        consult_opinions = [str(item.get("opinion", "")).strip() for item in consults if isinstance(item, dict)]
        department_evidence = [
            working,
            *objective_findings,
            *consult_opinions,
        ]
        responsible_department = normalize_department(
            infer_department_from_texts(
                department_evidence,
                default=default_department,
                prefer_clinical_department=True,
            ),
            default="general_medicine",
        )
        resolved_service = diagnostic_service or responsible_department

        if responsible_department in {"general_medicine", "internal_medicine", "radiology"} and resolved_service:
            responsible_department = normalize_department(resolved_service, default=responsible_department)

        if not resolved_service:
            resolved_service = responsible_department

        return responsible_department, resolved_service

    def integrate(self, state: dict, transcript: list[dict[str, str]], diagnosis_summary: dict[str, object]) -> dict[str, str]:
        working = str(diagnosis_summary.get("working_diagnosis", "")).strip()
        objective_findings = [str(item).strip() for item in diagnosis_summary.get("objective_findings", []) if str(item).strip()]
        consults = diagnosis_summary.get("specialty_consults", []) or []
        consult_opinions = [str(item.get("opinion", "")).strip() for item in consults if isinstance(item, dict)]
        responsible_department, diagnostic_service = self._resolve_department(
            working=working,
            objective_findings=objective_findings,
            consults=consults,
            default_department=str(diagnosis_summary.get("responsible_department", "")).strip() or "general_medicine",
            diagnostic_service=str(diagnosis_summary.get("diagnostic_service", "")).strip(),
        )

        objective_supported = self._extract_supported_diagnosis(objective_findings)
        if objective_supported:
            return {
                "final_diagnosis": objective_supported,
                "final_department": responsible_department,
                "diagnostic_service": diagnostic_service,
                "integration_rationale": "Final diagnosis was integrated from objective ER findings.",
                "used_llm": False,
            }

        consult_supported = self._extract_supported_diagnosis(consult_opinions)
        if consult_supported:
            return {
                "final_diagnosis": consult_supported,
                "final_department": responsible_department,
                "diagnostic_service": diagnostic_service,
                "integration_rationale": "Final diagnosis was integrated from specialty diagnostic input.",
                "used_llm": False,
            }

        if self._is_specific_diagnosis(working):
            return {
                "final_diagnosis": working,
                "final_department": responsible_department,
                "diagnostic_service": diagnostic_service,
                "integration_rationale": "Final diagnosis preserved the most specific specialty-refined working diagnosis because no stronger exact evidence was available.",
                "used_llm": False,
            }

        if settings.USE_LLM_FOR_FINAL_DIAGNOSIS_INTEGRATOR and consults and working:
            payload = {
                "working_diagnosis": working,
                "objective_findings": objective_findings[-4:],
                "specialty_consults": consults[-4:],
                "candidate_department": responsible_department,
                "instruction": (
                    "Return JSON with keys final_diagnosis, final_department, integration_rationale. "
                    "Use the most evidence-supported diagnosis. Keep final_department in the project taxonomy."
                ),
            }
            try:
                response = self.client.chat(
                    self.system_prompt,
                    json.dumps(payload, ensure_ascii=False, indent=2),
                ).strip()
                parsed = json.loads(response)
                final_diagnosis = str(parsed.get("final_diagnosis", "")).strip()
                final_department = normalize_department(
                    str(parsed.get("final_department", "")).strip(),
                    default=responsible_department,
                )
                integration_rationale = str(parsed.get("integration_rationale", "")).strip()
                if final_diagnosis and integration_rationale:
                    return {
                        "final_diagnosis": final_diagnosis,
                        "final_department": final_department,
                        "diagnostic_service": diagnostic_service,
                        "integration_rationale": integration_rationale,
                        "used_llm": True,
                    }
            except Exception:
                pass

        return {
            "final_diagnosis": working or "undifferentiated acute complaint",
            "final_department": responsible_department,
            "diagnostic_service": diagnostic_service,
            "integration_rationale": "Final diagnosis remained the best working diagnosis after ER and specialty review.",
            "used_llm": False,
        }
