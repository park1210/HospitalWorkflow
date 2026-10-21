import json
import re
from typing import Any

from app.config import settings
from app.llm.ollama_client import OllamaClient
from app.utils.prompt_loader import load_prompt
from app.core.clinical_observation import patient_observation
from app.llm.role_call import role_call, RoleCallError
from app.core.patient_facts import patient_facts, facts_for_question, selection_schema, render_selection


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
    def initial_utterance(self) -> dict:
        """Extractive v2 presentation: never interpret symptom values or times."""
        visible = self.case["synthea_v2_patient_input"]
        symptoms = visible["current_symptoms"]
        names = list(dict.fromkeys(s["symptom_name"] for s in symptoms))
        return {"utterance": "My symptoms are: " + ", ".join(names) + "." if names else "I am unsure.",
                "used_symptom_ids": [s["id"] for s in symptoms],
                "source_fact_ids": [s["id"] for s in symptoms], "grounded": True, "unknown": not bool(names),
                "method": "deterministic_extractive", "actual_llm_calls": 0}

    def answer_v2(self, question: str) -> dict:
        """Only explicit, supported question categories; missing details stay unknown."""
        visible = self.case["synthea_v2_patient_input"]
        if question == "What symptoms are you experiencing?":
            return self.initial_utterance()
        field = {"What allergies have you been told about?": "known_allergies",
                 "What medications do you know you take?": "known_medications",
                 "What medical history do you know about?": "known_history"}.get(question)
        facts = visible.get(field, []) if field else []
        return {"utterance": "My documented history includes: " + "; ".join(f["text"] for f in facts) + "." if facts else "I am unsure.",
                "source_fact_ids": [f["id"] for f in facts], "used_symptom_ids": [],
                "grounded": True, "unknown": not bool(facts),
                "method": "deterministic_extractive", "actual_llm_calls": 0}

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
        return any(re.search(r"\b" + re.escape(keyword) + r"\b", q) for keyword in clinician_keywords)

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

    def answer(self, question: str, state=None, *, required: bool = False) -> str:
        if "synthea_v2_patient_input" in self.case:
            self.last_grounding = self.answer_v2(question)
            return self.last_grounding["utterance"]
        fallback_answer = self._fallback_answer(question)
        if not required and not settings.USE_LLM_FOR_PATIENT_AGENT:
            return fallback_answer

        observation = patient_observation(self.case, state)
        facts = patient_facts(observation)
        if self._is_clinician_only_question(question):
            facts = []
        else:
            facts = facts_for_question(facts, question)
        payload = {
            "facts": facts,
            "doctor_question": question,
            "instruction": "Act as the patient. Select up to three fact_ids that answer the question. Return JSON with fact_ids and unknown only. For current symptoms use current facts; history describes the past. Do not add prose or infer any detail. If the answer is absent, or asks for clinician-only test results, return fact_ids=[] and unknown=true.",
        }
        audit = state.setdefault("llm_audit", []) if isinstance(state, dict) else getattr(state, "llm_audit", [])
        self.last_audit = audit
        selection = {}
        normalization = {}
        def validate_selection(raw):
            value = json.loads(raw)
            # Some backends do not enforce conditional schemas. Honor explicit
            # uncertainty without turning contradictory IDs into asserted facts.
            # Other malformed selections remain errors; no generated facts/retry.
            if isinstance(value, dict) and set(value) == {"fact_ids", "unknown"} and value.get("unknown") is True:
                ids = value.get("fact_ids")
                available = {f["id"] for f in facts}
                if (isinstance(ids, list) and 0 < len(ids) <= 3
                        and all(isinstance(i, str) and i in available for i in ids)
                        and len(set(ids)) == len(ids)):
                    normalization.update(reason="unknown_overrides_fact_ids", discarded_fact_ids=list(ids))
                    value = {"fact_ids": [], "unknown": True}
            answer = render_selection(json.dumps(value), facts)
            selection.update(value)
            return answer
        try:
            answer = role_call(self.client, role="patient", model=settings.OLLAMA_MODEL,
                             system="You select source facts to speak as a simulated patient. Follow the JSON selection contract.",
                             payload=payload, audit=audit,
                             validate=validate_selection, schema=selection_schema(facts))
            audit[-1]["grounding"] = {"mode": "extractive_selection", "facts": facts,
                                      "selection": selection, "rendered_answer": answer}
            if normalization:
                audit[-1]["output_normalization"] = normalization
            return answer
        except RoleCallError:
            if required:
                raise
            audit[-1]["fallback_used"] = True
            return "I am not sure about that."
        finally:
            if isinstance(state, dict):
                state["llm_call_count"] = state.get("llm_call_count", 0) + 1
            elif state is not None and hasattr(state, "llm_call_count"):
                state.llm_call_count += 1
