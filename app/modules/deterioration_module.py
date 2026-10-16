from __future__ import annotations

from typing import Any
import math


class DeteriorationModule:
    VITAL_DELTA_KEYS = {
        "sbp_delta": ("sbp", "systolic_bp"),
        "systolic_bp_delta": ("sbp", "systolic_bp"),
        "pain_score_delta": ("pain_score",),
        "heart_rate_delta": ("heart_rate", "hr", "pulse"),
        "respiratory_rate_delta": ("respiratory_rate", "rr"),
        "temperature_delta": ("temperature", "temp"),
        "spo2_delta": ("spo2", "oxygen_saturation", "o2_sat"),
    }

    def _to_float(self, value: Any) -> float | None:
        try:
            number = float(str(value).strip())
            return number if math.isfinite(number) else None
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

    def _apply_vital_delta(self, vitals: dict[str, Any], field_names: tuple[str, ...], delta: float) -> bool:
        for field_name in field_names:
            current = self._to_float(vitals.get(field_name))
            if current is not None:
                value = current + delta
                if value < 0 or (field_names[0] == "spo2" and value > 100) or (field_names[0] == "pain_score" and value > 10):
                    return False
                self._set_vital(vitals, field_name, round(value, 2))
                return True
        return False

    def _set_vital(self, vitals, name, value):
        aliases = next((keys for keys in self.VITAL_DELTA_KEYS.values() if name in keys), (name,))
        for key in aliases:
            if key in vitals or key == name:
                vitals[key] = value

    def _apply_effect(self, state: Any, effect: dict[str, Any], *, event_type: str, reason: str) -> dict[str, Any]:
        vitals = dict(getattr(state, "vital_signs", {}) or {})
        applied_effect: dict[str, Any] = {}
        gaps = []
        for name, value in effect.get("vital_values", {}).items():
            number = self._to_float(value)
            if number is None or number < 0 or (name in {"spo2", "oxygen_saturation"} and number > 100):
                gaps.append({"field": name, "reason": "invalid_absolute_value"})
                continue
            self._set_vital(vitals, name, number)
            applied_effect.setdefault("vital_values", {})[name] = number
        for effect_key, field_names in self.VITAL_DELTA_KEYS.items():
            delta = self._to_float(effect.get(effect_key))
            if delta is None:
                continue
            if self._apply_vital_delta(vitals, field_names, delta):
                applied_effect[effect_key] = delta
            else:
                gaps.append({"field": field_names[0], "reason": "missing_baseline_or_invalid_result"})

        new_symptoms = [str(item).strip() for item in effect.get("new_symptoms", []) if str(item).strip()]
        if new_symptoms:
            applied_effect["new_symptoms"] = new_symptoms
            state.current_symptoms = list(dict.fromkeys([*getattr(state, "current_symptoms", []), *new_symptoms]))

        resolved = effect.get("resolved_symptoms", [])
        if resolved:
            state.current_symptoms = [s for s in getattr(state, "current_symptoms", []) if s not in resolved]
            applied_effect["resolved_symptoms"] = list(resolved)

        if "blood_pressure" in vitals:
            sbp = vitals.get("sbp", vitals.get("systolic_bp"))
            dbp = vitals.get("diastolic_bp")
            if self._to_float(sbp) is not None and self._to_float(dbp) is not None:
                vitals["blood_pressure"] = f"{float(sbp):g}/{float(dbp):g}"
            else:
                vitals.pop("blood_pressure", None)
        setattr(state, "vital_signs", vitals)
        if effect.get("health_state") in {"Stable", "Worsening", "Critical"} and hasattr(state, "health_state"):
            state.health_state = effect["health_state"]
            applied_effect["health_state"] = state.health_state
        return {
            "event_type": event_type,
            "reason": reason,
            "applied_effect": applied_effect,
            "updated_vitals": vitals,
            "data_gaps": gaps,
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
            minute = int(event.get("minute", -1))
            arrival = int(getattr(state, "arrival_time_min", 0))
            if minute < 0 or not (start_time_min - arrival < minute <= end_time_min - arrival
                                  or minute == 0 and start_time_min == arrival <= end_time_min):
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
            threshold = int(trigger.get("if_unaddressed_for_minutes", -1))
            elapsed = end_time_min - int(getattr(state, "arrival_time_min", 0))
            if threshold < 0 or elapsed < threshold:
                continue
            # Only an explicit matching intervention suppresses this condition.
            treatment_id = trigger.get("addressed_by")
            if treatment_id and any(t.get("id") == treatment_id and t.get("effective_min", end_time_min + 1) <= end_time_min
                                    for t in getattr(state, "interventions", [])):
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

    def apply_interventions(self, case, state, end_time_min):
        """Apply only explicitly supplied effects; never infer drug efficacy."""
        specs = case.get("temporal_profile", {}).get("interventions", {})
        events = []
        for treatment in getattr(state, "interventions", []):
            key = f"intervention:{treatment['id']}:{treatment['time_min']}"
            if treatment["effective_min"] > end_time_min or key in state.applied_temporal_event_keys:
                continue
            spec = specs[treatment["id"]]
            events.append(self._apply_effect(state, spec["effect"], event_type="intervention_response",
                          reason=f"Configured effect of {treatment['id']} became due."))
            state.applied_temporal_event_keys.append(key)
        return events

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
        applied_events.extend(self._apply_default_progression(state,
            end_time_min=end_time_min - int(getattr(state, "arrival_time_min", 0))))

        for event in applied_events:
            event["triggering_action"] = str(triggering_action).strip()

        return {
            "risk": risk,
            "applied_events": applied_events,
            "updated_vitals": dict(getattr(state, "vital_signs", {}) or {}),
        }
