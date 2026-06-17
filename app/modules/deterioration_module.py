from __future__ import annotations

from typing import Any


class DeteriorationModule:
    VITAL_DELTA_KEYS = {
        "sbp_delta": ("sbp", "systolic_bp"),
        "heart_rate_delta": ("heart_rate", "hr", "pulse"),
        "respiratory_rate_delta": ("respiratory_rate", "rr"),
        "temperature_delta": ("temperature", "temp"),
        "spo2_delta": ("spo2", "oxygen_saturation", "o2_sat"),
    }

    def _to_float(self, value: Any) -> float | None:
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return None

    def _derive_risk(self, case: dict[str, Any], state: Any) -> str:
        temporal_profile = case.get("temporal_profile", {}) if isinstance(case.get("temporal_profile", {}), dict) else {}
        deterioration_model = (
            temporal_profile.get("deterioration_model", {})
            if isinstance(temporal_profile.get("deterioration_model", {}), dict)
            else {}
        )
        configured = str(deterioration_model.get("baseline_risk", "")).strip().lower()
        if configured:
            return configured

        triage_level = int(getattr(state, "triage_level", 3) or 3)
        if getattr(state, "needs_resuscitation_now", False) or triage_level <= 1:
            return "high"
        if triage_level == 2:
            return "moderate"
        if triage_level == 3:
            return "low"
        return "minimal"

    def _apply_vital_delta(self, vitals: dict[str, Any], field_names: tuple[str, ...], delta: float) -> None:
        for field_name in field_names:
            current = self._to_float(vitals.get(field_name))
            if current is not None:
                vitals[field_name] = round(current + delta, 2)
                return
        vitals[field_names[0]] = round(delta, 2)

    def _apply_effect(self, state: Any, effect: dict[str, Any], *, event_type: str, reason: str) -> dict[str, Any]:
        vitals = dict(getattr(state, "vital_signs", {}) or {})
        applied_effect: dict[str, Any] = {}
        for effect_key, field_names in self.VITAL_DELTA_KEYS.items():
            delta = self._to_float(effect.get(effect_key))
            if delta is None:
                continue
            self._apply_vital_delta(vitals, field_names, delta)
            applied_effect[effect_key] = delta

        new_symptoms = [str(item).strip() for item in effect.get("new_symptoms", []) if str(item).strip()]
        if new_symptoms:
            applied_effect["new_symptoms"] = new_symptoms

        setattr(state, "vital_signs", vitals)
        return {
            "event_type": event_type,
            "reason": reason,
            "applied_effect": applied_effect,
            "updated_vitals": vitals,
        }

    def _apply_natural_history_events(
        self,
        case: dict[str, Any],
        state: Any,
        *,
        start_time_min: int,
        end_time_min: int,
    ) -> list[dict[str, Any]]:
        temporal_profile = case.get("temporal_profile", {}) if isinstance(case.get("temporal_profile", {}), dict) else {}
        events = temporal_profile.get("natural_history_events", []) if isinstance(temporal_profile.get("natural_history_events", []), list) else []
        applied: list[dict[str, Any]] = []
        applied_keys = list(getattr(state, "applied_temporal_event_keys", []) or [])

        for index, event in enumerate(events):
            if not isinstance(event, dict):
                continue
            minute = int(event.get("minute", -1) or -1)
            if minute < 0 or not (start_time_min < minute <= end_time_min):
                continue
            event_key = f"natural_history:{index}:{minute}"
            if event_key in applied_keys:
                continue
            changes = event.get("changes", {}) if isinstance(event.get("changes", {}), dict) else {}
            event_type = str(event.get("event_type", "natural_history")).strip() or "natural_history"
            applied_event = self._apply_effect(
                state,
                changes,
                event_type=event_type,
                reason=f"Natural history event reached minute {minute}.",
            )
            applied_event["minute"] = minute
            applied.append(applied_event)
            applied_keys.append(event_key)

        state.applied_temporal_event_keys = applied_keys
        return applied

    def _apply_configured_triggers(
        self,
        case: dict[str, Any],
        state: Any,
        *,
        end_time_min: int,
    ) -> list[dict[str, Any]]:
        temporal_profile = case.get("temporal_profile", {}) if isinstance(case.get("temporal_profile", {}), dict) else {}
        deterioration_model = (
            temporal_profile.get("deterioration_model", {})
            if isinstance(temporal_profile.get("deterioration_model", {}), dict)
            else {}
        )
        triggers = deterioration_model.get("triggers", []) if isinstance(deterioration_model.get("triggers", []), list) else []
        applied: list[dict[str, Any]] = []
        applied_keys = list(getattr(state, "applied_temporal_event_keys", []) or [])

        for index, trigger in enumerate(triggers):
            if not isinstance(trigger, dict):
                continue
            threshold = int(trigger.get("if_unaddressed_for_minutes", -1) or -1)
            if threshold < 0 or end_time_min < threshold:
                continue
            trigger_key = f"deterioration_trigger:{index}:{threshold}"
            if trigger_key in applied_keys:
                continue
            effect = trigger.get("effect", {}) if isinstance(trigger.get("effect", {}), dict) else {}
            rationale = str(trigger.get("rationale", "")).strip() or f"Configured deterioration trigger reached minute {threshold}."
            applied_event = self._apply_effect(
                state,
                effect,
                event_type="configured_deterioration",
                reason=rationale,
            )
            applied_event["minute"] = threshold
            applied.append(applied_event)
            applied_keys.append(trigger_key)

        state.applied_temporal_event_keys = applied_keys
        return applied

    def _apply_default_progression(self, state: Any, *, end_time_min: int) -> list[dict[str, Any]]:
        applied: list[dict[str, Any]] = []
        applied_keys = list(getattr(state, "applied_temporal_event_keys", []) or [])
        risk = str(getattr(state, "deterioration_risk", "")).strip().lower()
        objective_count = len(list(getattr(state, "objective_findings", []) or []))
        stabilized = bool(getattr(state, "stabilized_after_intervention", True))
        unstable = bool(getattr(state, "needs_resuscitation_now", False) or getattr(state, "is_immediately_unstable", False))
        final_diagnosis = str(getattr(state, "final_diagnosis", "")).strip()

        if unstable and not stabilized and end_time_min >= 5:
            trigger_key = "default_progression:unstable_5"
            if trigger_key not in applied_keys:
                applied_event = self._apply_effect(
                    state,
                    {
                        "heart_rate_delta": 6,
                        "respiratory_rate_delta": 2,
                        "sbp_delta": -6,
                        "spo2_delta": -2,
                    },
                    event_type="default_deterioration",
                    reason="An unstable patient continued to progress before being fully stabilized.",
                )
                applied_event["minute"] = 5
                applied.append(applied_event)
                applied_keys.append(trigger_key)

        if not final_diagnosis and objective_count == 0 and risk in {"high", "moderate"} and end_time_min >= 30:
            trigger_key = "default_progression:delayed_workup_30"
            if trigger_key not in applied_keys:
                applied_event = self._apply_effect(
                    state,
                    {
                        "heart_rate_delta": 4,
                        "temperature_delta": 0.2,
                    },
                    event_type="default_deterioration",
                    reason="The patient remained diagnostically unresolved long enough for mild physiologic worsening.",
                )
                applied_event["minute"] = 30
                applied.append(applied_event)
                applied_keys.append(trigger_key)

        state.applied_temporal_event_keys = applied_keys
        return applied

    def advance(
        self,
        case: dict[str, Any],
        state: Any,
        *,
        start_time_min: int,
        end_time_min: int,
        triggering_action: str,
    ) -> dict[str, Any]:
        risk = self._derive_risk(case, state)
        state.deterioration_risk = risk

        applied_events: list[dict[str, Any]] = []
        applied_events.extend(
            self._apply_natural_history_events(
                case,
                state,
                start_time_min=start_time_min,
                end_time_min=end_time_min,
            )
        )
        applied_events.extend(self._apply_configured_triggers(case, state, end_time_min=end_time_min))
        applied_events.extend(self._apply_default_progression(state, end_time_min=end_time_min))

        for event in applied_events:
            event["triggering_action"] = str(triggering_action).strip()

        return {
            "risk": risk,
            "applied_events": applied_events,
            "updated_vitals": dict(getattr(state, "vital_signs", {}) or {}),
        }
