from __future__ import annotations

from typing import Any

class AssessmentModule:
    SYNDROME_RULES = {
        "cardiovascular": {
            "keywords": ["chest pain", "palpitation", "syncope", "presyncope", "tachycardia", "arrhythmia"],
            "label": "possible cardiovascular emergency",
            "family": "cardiorespiratory",
            "department_hints": {"cardiology": 1.0, "internal_medicine": 0.5},
            "test_keywords": ["ecg", "troponin", "blood"],
        },
        "respiratory": {
            "keywords": ["shortness of breath", "dyspnea", "hypoxia", "cough", "wheezing", "hemoptysis"],
            "label": "possible respiratory compromise",
            "family": "cardiorespiratory",
            "department_hints": {"pulmonology": 1.0, "internal_medicine": 0.5},
            "test_keywords": ["xray", "x-ray", "imaging", "blood"],
        },
        "abdominal_gi": {
            "keywords": ["abdominal pain", "vomiting", "melena", "hematemesis", "hematochezia", "constipation", "distension"],
            "label": "acute abdominal or gastrointestinal problem",
            "family": "abdominopelvic",
            "department_hints": {"surgery": 0.8, "gastroenterology": 0.8, "internal_medicine": 0.4},
            "test_keywords": ["blood", "urine", "ct", "ultrasound", "imaging", "xray", "x-ray"],
        },
        "neurologic": {
            "keywords": ["weakness", "diplopia", "seizure", "confusion", "headache", "ptosis", "ataxia", "vertigo"],
            "label": "possible neurologic process",
            "family": "neurologic",
            "department_hints": {"neurology": 1.0, "internal_medicine": 0.3},
            "test_keywords": ["mri", "ct", "electromyography", "blood", "imaging"],
        },
        "spinal_radicular": {
            "keywords": ["back pain", "radiating down", "radiating to the leg", "nerve root", "numbness", "paresthesia", "radicular"],
            "label": "possible spinal or radicular neurologic process",
            "family": "neuromusculoskeletal",
            "department_hints": {"neurology": 0.7, "orthopedics": 0.7, "internal_medicine": 0.2},
            "test_keywords": ["mri", "ct", "xray", "x-ray", "imaging"],
        },
        "renal_urinary": {
            "keywords": ["flank pain", "dysuria", "hematuria", "proteinuria", "creatinine", "renal", "kidney", "urinary"],
            "label": "possible renal or urinary process",
            "family": "genitourinary",
            "department_hints": {"nephrology": 0.9, "urology": 0.7, "internal_medicine": 0.3},
            "test_keywords": ["urine", "blood", "ultrasound", "ct", "imaging"],
        },
        "infectious_inflammatory": {
            "keywords": ["fever", "chills", "infection", "rash", "inflammatory", "fatigue", "malaise"],
            "label": "possible infectious or inflammatory problem",
            "family": "systemic_inflammatory",
            "department_hints": {"infectious_disease": 0.7, "internal_medicine": 0.7, "general_medicine": 0.5},
            "test_keywords": ["blood", "urine", "xray", "x-ray", "imaging"],
        },
        "gynecologic": {
            "keywords": ["pelvic pain", "vaginal bleeding", "pregnan", "amenorrhea", "adnexal", "uterine"],
            "label": "possible gynecologic process",
            "family": "abdominopelvic",
            "department_hints": {"obstetrics_gynecology": 1.0, "internal_medicine": 0.3},
            "test_keywords": ["ultrasound", "urine", "blood", "imaging"],
        },
        "musculoskeletal": {
            "keywords": ["joint pain", "fracture", "dislocation", "musculoskeletal", "tendon", "ligament", "hip pain"],
            "label": "possible structural musculoskeletal process",
            "family": "neuromusculoskeletal",
            "department_hints": {"orthopedics": 1.0, "rheumatology": 0.4, "internal_medicine": 0.2},
            "test_keywords": ["xray", "x-ray", "mri", "ct", "imaging"],
        },
        "ophthalmic": {
            "keywords": ["vision loss", "eye pain", "ocular", "blurred vision", "eye redness"],
            "label": "possible ophthalmic process",
            "family": "neurologic",
            "department_hints": {"ophthalmology": 1.0, "neurology": 0.3},
            "test_keywords": ["imaging", "mri", "ct", "blood"],
        },
    }

    def _normalize(self, text: str) -> str:
        return " ".join(str(text).strip().split())

    def _score_syndromes(self, complaint: str, history: str) -> list[tuple[str, int]]:
        text = f"{complaint} {history}".lower()
        scores: list[tuple[str, int]] = []
        for syndrome, rule in self.SYNDROME_RULES.items():
            score = sum(1 for keyword in rule["keywords"] if keyword in text)
            if score > 0:
                scores.append((syndrome, score))
        scores.sort(key=lambda item: item[1], reverse=True)
        return scores

    def _suggest_problem_list(self, syndrome_scores: list[tuple[str, int]], complaint: str) -> list[str]:
        problems: list[str] = []
        for syndrome, score in syndrome_scores[:3]:
            if score <= 0:
                continue
            label = str(self.SYNDROME_RULES[syndrome]["label"]).strip()
            if label and label not in problems:
                problems.append(label)

        if not problems and complaint:
            problems.append("undifferentiated acute complaint")
        return problems[:4]

    def _suggest_initial_tests(self, syndrome_scores: list[tuple[str, int]], available_tests: list[str]) -> list[str]:
        ranked: list[str] = []

        def add_if_match(keywords: list[str]) -> None:
            for section in available_tests:
                normalized = section.lower()
                if any(keyword in normalized for keyword in keywords) and section not in ranked:
                    ranked.append(section)

        prioritized_syndromes = [syndrome for syndrome, _ in syndrome_scores[:2]]
        for syndrome in prioritized_syndromes:
            add_if_match(list(self.SYNDROME_RULES[syndrome]["test_keywords"]))

        for section in available_tests:
            if section not in ranked:
                ranked.append(section)
        return ranked[:4]

    def _build_department_signal_scores(self, syndrome_scores: list[tuple[str, int]]) -> dict[str, float]:
        scores: dict[str, float] = {}
        for syndrome, score in syndrome_scores[:4]:
            if score <= 0:
                continue
            hints = self.SYNDROME_RULES[syndrome].get("department_hints", {}) or {}
            for department, weight in hints.items():
                normalized_department = str(department).strip()
                if not normalized_department:
                    continue
                scores[normalized_department] = scores.get(normalized_department, 0.0) + (float(score) * float(weight))
        return scores

    def _build_family_signal_scores(self, syndrome_scores: list[tuple[str, int]]) -> dict[str, float]:
        scores: dict[str, float] = {}
        for syndrome, score in syndrome_scores[:4]:
            if score <= 0:
                continue
            family = str(self.SYNDROME_RULES[syndrome].get("family", "")).strip()
            if family:
                scores[family] = scores.get(family, 0.0) + float(score)
        return scores

    def _infer_suspected_system(self, family_signal_scores: dict[str, float]) -> str:
        if not family_signal_scores:
            return "undifferentiated"
        return max(family_signal_scores.items(), key=lambda item: item[1])[0]

    def run(self, case: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        patient_visible = case.get("patient_visible_info", {})
        doctor_visible = case.get("doctor_visible_info", {})
        history = self._normalize(patient_visible.get("history", ""))
        complaint = self._normalize(doctor_visible.get("chief_complaint", ""))
        available_tests = [str(item).strip() for item in case.get("meta", {}).get("available_test_sections", []) if str(item).strip()]

        syndrome_scores = self._score_syndromes(complaint, history)
        working_problem_list = self._suggest_problem_list(syndrome_scores, complaint)
        recommended_initial_tests = self._suggest_initial_tests(syndrome_scores, available_tests)
        department_signal_scores = self._build_department_signal_scores(syndrome_scores)
        family_signal_scores = self._build_family_signal_scores(syndrome_scores)

        red_flags: list[str] = []
        vitals = state.get("vital_signs", {}) if isinstance(state.get("vital_signs", {}), dict) else {}
        for key in ("systolic_bp", "oxygen_saturation", "heart_rate", "respiratory_rate"):
            if key in vitals:
                red_flags.append(f"abnormal vital sign check needed: {key}")

        if any(keyword in f"{complaint} {history}".lower() for keyword in ["worsening", "sudden", "severe", "acute"]):
            red_flags.append("sudden or severe symptom progression")

        suspected_system = self._infer_suspected_system(family_signal_scores)

        return {
            "primary_problem": working_problem_list[0] if working_problem_list else "undifferentiated acute complaint",
            "working_problem_list": working_problem_list,
            "suspected_system": suspected_system,
            "family_signal_scores": family_signal_scores,
            "department_signal_scores": department_signal_scores,
            "red_flags": red_flags[:4],
            "recommended_initial_tests": recommended_initial_tests,
            "needs_immediate_test": bool(recommended_initial_tests),
            "assessment_rationale": "ER assessment generated broad syndrome candidates and a low-cost initial test bundle without locking the case into a single specialty too early.",
        }
