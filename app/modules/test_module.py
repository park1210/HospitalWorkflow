from __future__ import annotations

from typing import Any
import re


TEST_TERM_ALIASES = {
    "mri": "imaging",
    "ct": "imaging",
    "xray": "imaging",
    "x-ray": "imaging",
    "ultrasound": "imaging",
    "scan": "imaging",
    "radiograph": "imaging",
    "emg": "electromyography",
    "electrodiagnostic": "electromyography",
    "cbc": "blood_tests",
    "cmp": "blood_tests",
    "bmp": "blood_tests",
    "labs": "blood_tests",
    "lab": "blood_tests",
    "serology": "blood_tests",
    "antibody": "blood_tests",
    "blood": "blood_tests",
    "urine": "urinalysis",
    "urinalysis": "urinalysis",
}


class TestModule:
    def __init__(self, case: dict[str, Any]) -> None:
        self.hidden_exam_results = case.get("hidden_exam_results", {})
        self.hidden_test_results = case.get("hidden_test_results", {})

    def _normalize_text(self, value: str) -> str:
        text = str(value).strip().lower().replace("_", " ")
        text = re.sub(r"[^a-z0-9\s\-]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _normalized_terms(self, value: str) -> set[str]:
        text = self._normalize_text(value)
        if not text:
            return set()

        terms = set(text.split())
        expanded_terms = set(terms)
        for term in terms:
            if term in TEST_TERM_ALIASES:
                expanded_terms.add(TEST_TERM_ALIASES[term])
        if "electromyography" in text:
            expanded_terms.add("electromyography")
        if "blood test" in text or "blood tests" in text:
            expanded_terms.add("blood_tests")
        if "vital signs" in text:
            expanded_terms.add("vital_signs")
        if "neuro exam" in text or "neurological examination" in text:
            expanded_terms.add("neurological_examination")
        return expanded_terms

    def _score_section_match(self, requested_name: str, section_name: str) -> int:
        normalized_request = self._normalize_text(requested_name)
        normalized_section = self._normalize_text(section_name)
        if not normalized_request or not normalized_section:
            return 0
        if normalized_request == normalized_section:
            return 100
        if normalized_request in normalized_section or normalized_section in normalized_request:
            return 80

        request_terms = self._normalized_terms(requested_name)
        section_terms = self._normalized_terms(section_name)
        overlap = request_terms & section_terms
        if not overlap:
            return 0

        score = len(overlap) * 10
        if any(term in overlap for term in {"imaging", "electromyography", "blood_tests", "urinalysis"}):
            score += 15
        return score

    def _resolve_from_sections(self, sections: dict[str, Any], requested_name: str) -> tuple[str, str]:
        if not str(requested_name).strip():
            return "", "No requested section provided."

        best_section_name = ""
        best_section_value: Any = ""
        best_score = 0
        for section_name, section_value in sections.items():
            score = self._score_section_match(requested_name, str(section_name))
            if score > best_score:
                best_score = score
                best_section_name = str(section_name).strip()
                best_section_value = section_value

        if best_score >= 15:
            return best_section_name, str(best_section_value)
        return "", f"No matching result found for '{requested_name}'."

    def request_test(self, test_name: str) -> tuple[str, str]:
        resolved_name, result_text = self._resolve_from_sections(self.hidden_test_results, test_name)
        if resolved_name:
            return resolved_name, result_text
        return self._resolve_from_sections(self.hidden_exam_results, test_name)
