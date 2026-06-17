from __future__ import annotations

from typing import Any


CRITICAL_KEYWORDS = {
    "cardiac arrest",
    "respiratory arrest",
    "shock",
    "unresponsive",
    "seizure",
    "septic shock",
}

HIGH_RISK_KEYWORDS = {
    "stroke",
    "myocardial infarction",
    "chest pain",
    "shortness of breath",
    "altered mental status",
    "syncope",
    "hemorrhage",
    "trauma",
}


class TriageModule:
    def _normalize(self, text: str) -> str:
        return " ".join(str(text).strip().lower().split())

    def _to_float(self, value: Any) -> float | None:
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return None

    def _detect_vital_instability(self, vitals: dict[str, Any]) -> tuple[bool, list[str]]:
        flags: list[str] = []
        sbp = self._to_float(vitals.get("systolic_bp") or vitals.get("sbp") or vitals.get("blood_pressure_systolic"))
        hr = self._to_float(vitals.get("heart_rate") or vitals.get("hr") or vitals.get("pulse"))
        rr = self._to_float(vitals.get("respiratory_rate") or vitals.get("rr"))
        spo2 = self._to_float(vitals.get("oxygen_saturation") or vitals.get("spo2") or vitals.get("o2_sat"))
        temp = self._to_float(vitals.get("temperature") or vitals.get("temp"))

        if sbp is not None and sbp < 90:
            flags.append("hypotension")
        if hr is not None and hr >= 130:
            flags.append("severe tachycardia")
        if rr is not None and rr >= 30:
            flags.append("respiratory distress")
        if spo2 is not None and spo2 < 90:
            flags.append("hypoxemia")
        if temp is not None and temp >= 39.5:
            flags.append("high fever")
        return bool(flags), flags

    def run(self, case: dict[str, Any]) -> dict[str, Any]:
        doctor_visible = case.get("doctor_visible_info", {})
        complaint = self._normalize(doctor_visible.get("chief_complaint", ""))
        arrival_info = self._normalize(doctor_visible.get("arrival_info", ""))
        triage_clues = " ".join(
            self._normalize(item)
            for item in doctor_visible.get("triage_clues", [])
            if str(item).strip()
        )
        vitals = doctor_visible.get("initial_vitals", {}) if isinstance(doctor_visible.get("initial_vitals", {}), dict) else {}

        text = " ".join(part for part in [complaint, arrival_info, triage_clues] if part)
        unstable_by_vitals, vital_flags = self._detect_vital_instability(vitals)

        if any(keyword in text for keyword in CRITICAL_KEYWORDS) or unstable_by_vitals:
            rationale = "Triage marked the case as immediately unstable because of critical complaint or abnormal vital signs."
            return {
                "triage_level": 1 if unstable_by_vitals or any(keyword in text for keyword in CRITICAL_KEYWORDS) else 2,
                "is_unstable": True,
                "needs_resuscitation_now": True,
                "red_flags": vital_flags,
                "triage_rationale": rationale,
            }

        if any(keyword in text for keyword in HIGH_RISK_KEYWORDS):
            return {
                "triage_level": 2,
                "is_unstable": False,
                "needs_resuscitation_now": False,
                "red_flags": vital_flags,
                "triage_rationale": "Triage identified a high-risk presentation needing rapid ER evaluation.",
            }

        if vitals or complaint:
            return {
                "triage_level": 3,
                "is_unstable": False,
                "needs_resuscitation_now": False,
                "red_flags": vital_flags,
                "triage_rationale": "Triage assigned a standard ER workup pathway with multiple likely resources.",
            }

        return {
            "triage_level": 4,
            "is_unstable": False,
            "needs_resuscitation_now": False,
            "red_flags": vital_flags,
            "triage_rationale": "Triage found no immediate instability and no strong high-risk signal at arrival.",
        }
