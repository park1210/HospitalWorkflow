"""Whether a case supplies explicit health severity transitions for DBER."""


def has_health_progression(case):
    profile = case.get("temporal_profile", {})
    if profile.get("flow_deterioration"):
        return True
    effects = [event.get("changes", {}) for event in profile.get("natural_history_events", [])]
    effects += [trigger.get("effect", {}) for trigger in profile.get("deterioration_model", {}).get("triggers", [])]
    return any(effect.get("health_state") in {"Worsening", "Critical"} for effect in effects)
