from __future__ import annotations

from typing import Any


class StabilizationModule:
    def run(self, case: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        complaint = str(case.get("doctor_visible_info", {}).get("chief_complaint", "")).lower()
        vitals = state.get("vital_signs", {}) if isinstance(state.get("vital_signs", {}), dict) else {}
        actions: list[str] = []

        try:
            spo2 = float(str(vitals.get("oxygen_saturation") or vitals.get("spo2") or ""))
        except (TypeError, ValueError):
            spo2 = None
        try:
            sbp = float(str(vitals.get("systolic_bp") or vitals.get("sbp") or ""))
        except (TypeError, ValueError):
            sbp = None

        if spo2 is not None and spo2 < 92:
            actions.append("supplemental oxygen")
        if sbp is not None and sbp < 90:
            actions.append("intravenous fluid resuscitation")
        if any(keyword in complaint for keyword in ["pain", "fracture", "abdominal"]):
            actions.append("pain control")
        if any(keyword in complaint for keyword in ["bleeding", "hemorrhage"]):
            actions.append("bleeding control and urgent reassessment")

        return {
            "stabilization_actions": actions,
            "monitoring_started": bool(actions) or bool(state.get("is_immediately_unstable")),
            "stabilized_after_intervention": not bool(state.get("is_immediately_unstable")) or bool(actions),
            "post_stabilization_status": (
                "initial stabilization performed before continued ER workup"
                if actions
                else "no immediate stabilization procedure required"
            ),
        }
