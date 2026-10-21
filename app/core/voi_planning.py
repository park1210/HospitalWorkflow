"""Cost-free finite-horizon Bayesian VoI; at most one use per action."""
import math
from functools import lru_cache
from app.core.diagnostic_belief import distribution, posterior, entropy, terminal_choice


def outcome_branches(belief, action):
    branches = []
    for outcome in action['outcomes']:
        likelihood = outcome['likelihood']
        if set(likelihood) != set(belief) or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in likelihood.values()):
            raise ValueError('Invalid outcome likelihood')
        mass = sum(belief[d] * likelihood[d] for d in belief)
        updated = posterior(belief, likelihood)[0] if mass > 0 else None
        branches.append({'outcome_id': outcome['id'], 'probability': mass, 'posterior': updated})
    for d in belief:
        if not math.isclose(sum(o['likelihood'][d] for o in action['outcomes']), 1, abs_tol=1e-9):
            raise ValueError('Outcome probabilities must sum to one')
    return branches


def plan_voi(belief, actions, terminal_utility, *, horizon=1, max_states=20000):
    distribution(belief)
    if type(horizon) is not int or not 1 <= horizon <= 3:
        raise ValueError('horizon must be 1..3')
    if len(actions) > 12 or len({a['id'] for a in actions}) != len(actions):
        raise ValueError('Too many actions or duplicate IDs')
    for a in actions:
        outcome_branches(belief, a)
    baseline = terminal_choice(belief, terminal_utility)[1]
    order = sorted(belief)
    states = [0]

    @lru_cache(None)
    def v(probabilities, remaining, depth):
        states[0] += 1
        if states[0] > max_states:
            raise ValueError('VoI state limit exceeded')
        b = dict(zip(order, probabilities))
        terminal = terminal_choice(b, terminal_utility)[1]
        if depth == 0 or not remaining:
            return terminal
        best = terminal
        for idx in remaining:
            others = tuple(j for j in remaining if j != idx)
            q = sum(o['probability'] * v(tuple(o['posterior'][d] for d in order), others, depth-1)
                    for o in outcome_branches(b, actions[idx]) if o['probability'] > 0)
            best = max(best, q)
        return best

    scores = []
    indices = tuple(range(len(actions)))
    for idx, action in enumerate(actions):
        others = tuple(j for j in indices if j != idx)
        branches = outcome_branches(belief, action)
        q = sum(o['probability'] * v(tuple(o['posterior'][d] for d in order), others, horizon-1)
                for o in branches if o['probability'] > 0)
        cond_entropy = sum(o['probability'] * entropy(o['posterior']) for o in branches if o['probability'] > 0)
        scores.append({'action_id': action['id'], 'q_value': q, 'expected_continuation_utility': q,
                       'voi': q-baseline, 'information_gain_nats': max(0, entropy(belief)-cond_entropy),
                       'cost_penalty': 0.0, 'cost_components': {}, 'outcomes': branches})
    scores.sort(key=lambda row: (-row['q_value'], row['action_id']))
    best = scores[0] if scores else None
    chosen = best['action_id'] if best and best['q_value'] > baseline + 1e-12 else None
    return {'horizon': horizon, 'selected_action_id': chosen,
            'selected_action_type': 'information_action' if chosen is not None else 'diagnose',
            'baseline_terminal_utility': baseline, 'optimal_value': max(baseline, best['q_value'] if best else baseline),
            'action_values': scores, 'evaluated_states': states[0], 'cost_model': 'none'}
