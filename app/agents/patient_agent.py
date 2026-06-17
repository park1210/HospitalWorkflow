import json
import re
from typing import Any

from app.config import settings
from app.llm.ollama_client import OllamaClient
from app.utils.prompt_loader import load_prompt


DEFAULT_PATIENT_SYSTEM_PROMPT = """
You are a patient in a hospital workflow simulation.
Answer only as the patient.

Rules:
- Use only the case facts shown to you.
- Do not reveal the diagnosis.
- Do not perform medical reasoning.
- If asked about labs, imaging, physical exam, or clinician-only findings, say you do not know.
- Keep answers short and natural.
"""


class PatientAgent:
    def __init__(self, case: dict[str, Any]) -> None:
        self.case = case
        self.patient_info = case.get("patient_visible_info", {})
        self.client = OllamaClient()
        self.system_prompt = load_prompt("patient_system.txt", DEFAULT_PATIENT_SYSTEM_PROMPT)

    def _normalize_question(self, question: str) -> str:
        return re.sub(r"\s+", " ", str(question).strip().lower())

    def _to_first_person(self, text: str) -> str:
        value = str(text).strip()
        if not value:
            return ""
        replacements = [
            (r"^the patient reports\s+", ""),
            (r"^the patient states\s+", ""),
            (r"^the patient notes\s+", ""),
            (r"^the patient describes\s+", ""),
            (r"^i presents\b", "I present"),
            (r"\bi presents\b", "I present"),
            (r"\bi reports\b", "I report"),
            (r"\bi states\b", "I state"),
            (r"\bi notes\b", "I note"),
            (r"\bthe patient\b", "I"),
            (r"\bshe notes that\b", "I notice that"),
            (r"\bhe notes that\b", "I notice that"),
            (r"\bshe reports\b", "I"),
            (r"\bhe reports\b", "I"),
            (r"\bshe has\b", "I have"),
            (r"\bhe has\b", "I have"),
            (r"\bshe is\b", "I am"),
            (r"\bhe is\b", "I am"),
            (r"\bshe\b", "I"),
            (r"\bhe\b", "I"),
            (r"\bher\b", "my"),
            (r"\bhis\b", "my"),
        ]
        for pattern, replacement in replacements:
            value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
        value = re.sub(r"\s+", " ", value).strip()
        if value:
            value = value[0].upper() + value[1:]
        return value

    def _to_spoken_history(self, text: str) -> str:
        value = self._to_first_person(text)
        if not value:
            return ""

        duration_match = re.match(
            r"^A[n]?\s+([0-9A-Za-z\- ]+?)\s+history of\s+(.+)$",
            value,
            flags=re.IGNORECASE,
        )
        if duration_match:
            duration = duration_match.group(1).strip()
            remainder = duration_match.group(2).strip()
            remainder = remainder[0].lower() + remainder[1:] if remainder else remainder
            return f"It started about {duration} ago with {remainder}"

        value = re.sub(r"^History of\s+", "", value, flags=re.IGNORECASE)
        return value

    def _history_sentences(self) -> list[str]:
        history = self._to_spoken_history(str(self.patient_info.get("history", "")).strip())
        if not history:
            return []
        return [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", history) if sentence.strip()]

    def _best_history_sentence(self, keywords: list[str]) -> str:
        sentences = self._history_sentences()
        lowered_keywords = [keyword.lower() for keyword in keywords if keyword]
        for sentence in sentences:
            lowered = sentence.lower()
            if any(keyword in lowered for keyword in lowered_keywords):
                return sentence
        return sentences[0] if sentences else ""

    def _is_patient_history_question(self, question: str) -> bool:
        q = self._normalize_question(question)
        history_keywords = [
            "when",
            "how long",
            "started",
            "onset",
            "since",
            "better",
            "worse",
            "activity",
            "rest",
            "improve",
            "change",
            "changed",
            "progress",
            "progression",
            "where",
            "point to where",
            "strongest",
            "location",
            "pain",
            "symptom",
            "main problem",
            "what happened",
            "what has been going on",
            "medical history",
            "past medical",
            "medication",
            "medicine",
            "drug",
            "social",
            "smoking",
            "alcohol",
            "work",
            "job",
            "other symptoms",
            "associated",
            "review of systems",
        ]
        return any(keyword in q for keyword in history_keywords)

    def _is_clinician_only_question(self, question: str) -> bool:
        q = self._normalize_question(question)
        clinician_keywords = [
            "physical exam",
            "examination finding",
            "vital sign",
            "blood pressure",
            "heart rate",
            "lab",
            "test result",
            "ct",
            "mri",
            "x-ray",
            "xray",
            "ultrasound",
            "scan",
            "imaging",
        ]
        return any(keyword in q for keyword in clinician_keywords)

    def _fallback_answer(self, question: str) -> str:
        q = self._normalize_question(question)
        symptoms = self.patient_info.get("symptoms", {})
        history = str(self.patient_info.get("history", "")).strip()
        ros = str(self.patient_info.get("review_of_systems", "")).strip()
        chief_complaint = str(self.patient_info.get("chief_complaint", "")).strip()
        associated = [str(item).strip() for item in symptoms.get("associated", []) if str(item).strip()]
        secondary = [str(item).strip() for item in symptoms.get("secondary", []) if str(item).strip()]

        if self._is_clinician_only_question(question) and not self._is_patient_history_question(question):
            return "I do not know those results. The doctor would need to examine me or order tests."

        if any(keyword in q for keyword in ["when", "how long", "started", "onset", "since"]):
            return self._best_history_sentence(["started", "month", "week", "day", "since", "ago"]) or self._to_spoken_history(history) or "I am not sure exactly when it started."
        if any(keyword in q for keyword in ["better", "worse", "activity", "rest", "improve"]):
            return self._best_history_sentence(["worse", "better", "activity", "rest", "improve", "after physical activity", "after rest", "fatigue", "fluctuate"]) or "It seems to change depending on what I am doing."
        if any(keyword in q for keyword in ["where", "point to where", "strongest", "location"]):
            return self._to_first_person(chief_complaint) or self._best_history_sentence(["left", "right", "upper", "lower", "arm", "leg", "eye", "chest", "abdomen", "back"]) or "It is mostly where I first noticed the symptoms."
        if any(keyword in q for keyword in ["what brings you", "what happened", "main problem", "symptom", "pain"]):
            summary = symptoms.get("summary", [])
            if summary:
                return self._to_first_person(", ".join(str(item) for item in summary if str(item).strip()))
            return self._to_spoken_history(history) or "I have not been feeling well."
        if any(keyword in q for keyword in ["medical history", "past medical"]):
            return self._to_first_person(str(self.patient_info.get("past_medical_history", "")).strip()) or "I do not have any major past medical history that I know of."
        if any(keyword in q for keyword in ["medication", "medicine", "drug"]):
            return self._to_first_person(str(self.patient_info.get("current_medications", "")).strip()) or "I am not taking any regular medications."
        if any(keyword in q for keyword in ["social", "smoking", "alcohol", "work", "job"]):
            return self._to_first_person(str(self.patient_info.get("social_history", "")).strip()) or "Nothing notable."
        if any(keyword in q for keyword in ["other symptoms", "associated", "review of systems"]):
            if associated:
                return self._to_first_person(", ".join(associated))
            if secondary:
                return self._to_first_person(", ".join(secondary))
            return self._to_first_person(ros) or "I do not think I have other symptoms."

        return self._best_history_sentence(["noticed", "started", "worse", "better", "changed"]) or self._to_spoken_history(history) or self._to_first_person(chief_complaint) or "I am not sure."

    def answer(self, question: str) -> str:
        fallback_answer = self._fallback_answer(question)
        if self._is_patient_history_question(question):
            return fallback_answer
        if self._is_clinician_only_question(question):
            return fallback_answer
        if not settings.USE_LLM_FOR_PATIENT_AGENT:
            return fallback_answer

        payload = {
            "patient_visible_info": self.patient_info,
            "doctor_question": question,
            "instruction": "Answer as the patient in 1 to 3 sentences using only patient_visible_info.",
        }
        try:
            response = self.client.chat(self.system_prompt, json.dumps(payload, ensure_ascii=False, indent=2)).strip()
            if response:
                return response
        except Exception:
            pass
        return fallback_answer
