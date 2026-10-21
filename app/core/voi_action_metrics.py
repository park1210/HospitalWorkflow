"""Independent held-out VoI action evaluation; gold never enters selection."""

def action_agreement(selected_action_ids, acceptable_action_ids):
    if len(selected_action_ids) != len(acceptable_action_ids):
        raise ValueError('Paired actions required')
    if not selected_action_ids:
        return None
    return sum(selected in set(acceptable) for selected, acceptable in zip(selected_action_ids, acceptable_action_ids)) / len(selected_action_ids)


def action_regret(selected_action_id, reference_values):
    """Reference values must come from independently validated outcomes."""
    if not reference_values or selected_action_id not in reference_values:
        return None
    return max(reference_values.values()) - reference_values[selected_action_id]
