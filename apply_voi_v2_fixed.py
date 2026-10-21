"""Generate complete updated HospitalWorkflow files from CURRENT local sources.
Run at repository root. Backups and all-or-nothing validation included.
"""
import ast
import hashlib
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent
# When run from extracted package directory nested within the repo, use cwd.
if not (ROOT/'app/core/information_value.py').exists():
    ROOT = Path.cwd()
IV = ROOT/'app/core/information_value.py'
IO = ROOT/'app/core/information_outcomes.py'
if not IV.exists() or not IO.exists():
    raise SystemExit('Run from HospitalWorkflow project root (app/core required).')


def replace_function(src, name, new):
    tree = ast.parse(src)
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    if len(nodes) != 1:
        raise RuntimeError('Expected one function: '+name)
    lines = src.splitlines(keepends=True)
    node=nodes[0]
    start = node.lineno-1
    end = node.end_lineno
    lines[start:end] = [new.strip()+'\n']
    return ''.join(lines)


def once(src, old, new, label):
    count = src.count(old)
    if count != 1:
        raise RuntimeError('%s: expected one match; got %d. Local source differs; no files changed.'%(label,count))
    return src.replace(old, new, 1)

VALUE_FUNC='''
def action_values(belief, actions, artifact):
    """Cost-free one-step VoI (backward-compatible output contract)."""
    from app.core.voi_planning import plan_voi
    utility = artifact.get('terminal_utility') or validation_utility(belief)
    result = plan_voi(belief, actions, utility, horizon=1)
    return sorted(result['action_values'], key=lambda r: (-r['voi'], r['action_id']))
'''
SELECT_FUNC='''
def select_action(candidates, *, selector, belief=None, artifact=None, specialist_proposal=None, seed=0):
    """Select actions without money/time/token cost, and honor horizon."""
    status = {'selector': selector, 'status': 'available', 'selected_action': None}
    if selector == 'specialist_heuristic':
        return {**status, 'selected_action': specialist_proposal}
    if selector == 'random':
        return {**status, 'selected_action': random.Random(seed).choice(candidates) if candidates else None}
    if selector not in {'bayesian_voi', 'information_gain'}:
        raise ValueError('Unknown action selector')
    if artifact is None or belief is None:
        return {**status, 'status': 'unavailable', 'reason': 'missing_outcome_model'}
    DiagnosisBelief(belief)
    modeled = {a['id']: a for a in artifact['actions']}
    if any(c['type'] != 'Diagnose' and c.get('outcome_model') not in modeled for c in candidates):
        return {**status, 'status': 'unavailable', 'reason': 'missing_action_outcome_model'}
    utility = artifact.get('terminal_utility') or validation_utility(belief)
    diagnosis, baseline = terminal_choice(belief, utility)
    available = [modeled[c['outcome_model']] for c in candidates if c['type'] != 'Diagnose']
    from app.core.voi_planning import plan_voi
    horizon = artifact.get('horizon', 1) if selector == 'bayesian_voi' else 1
    plan = plan_voi(belief, available, utility, horizon=horizon)
    scores = {r['action_id']: r for r in plan['action_values']}
    ranked=[]
    for c in candidates:
        if c['type'] == 'Diagnose':
            ranked.append({**c, 'target': diagnosis, 'q_value': baseline, 'voi': 0.0,
                           'cost_penalty': 0.0, 'cost_components': {}, 'information_gain_nats': 0.0})
        else:
            ranked.append({**c, **scores[c['outcome_model']]})
    metric = 'q_value' if selector == 'bayesian_voi' else 'information_gain_nats'
    ranked.sort(key=lambda r: (-r[metric], r['type'] != 'Diagnose', r['action_id']))
    if selector == 'bayesian_voi' and plan['selected_action_id'] is None:
        chosen = next((r for r in ranked if r['type'] == 'Diagnose'), None)
    else:
        chosen = ranked[0] if ranked else None
    return {**status, 'selected_action': chosen, 'values': ranked, 'horizon': horizon,
            'diagnose_value': baseline, 'utility_scope': 'supplied' if artifact.get('terminal_utility') else 'algorithm_validation_only'}
'''

source = IV.read_text(encoding='utf-8')
source = replace_function(source,'action_values',VALUE_FUNC)
source = replace_function(source,'select_action',SELECT_FUNC)
# Patch both existing/previously fixed forms without unfixing KeyError.
source = source.replace('all(normalized(q["question"]) != normalized(target) for q in runtime.question_history)',
                        'all(normalized(q.get("question", "")) != normalized(target) for q in runtime.question_history if isinstance(q, dict))')
# Both the original and already-patched horizon traces are valid.
old_horizon = 'candidates=selection["values"], horizon=1)'
new_horizon = 'candidates=selection["values"], horizon=selection.get("horizon", 1))'
if old_horizon in source:
    source = once(source, old_horizon, new_horizon, 'dynamic horizon trace')
elif source.count(new_horizon) != 1:
    raise RuntimeError(
        'dynamic horizon trace: neither supported form appears exactly once; '
        'no files changed. Please provide current information_value.py.'
    )
# Remove legacy artifacts from selection payload and trace; source JSON still backward-compatible.
source = source.replace('"cost": a["cost"],', '"cost": {},')
source = source.replace('cost_components=best["cost_components"], ', '')
# Avoid exposing fake cost data through the common candidate catalog.
source = source.replace('deepcopy(model["cost"]) if model else (0 if kind == "diagnose" else None)', '{}')
ast.parse(source)

model = IO.read_text(encoding='utf-8')
# v2 schema inputs are normalized to legacy validation shape internally; no cost contributes to policy.
marker='''        required = {"schema_version", "model_id", "revision", "provenance", "diagnoses", "prior", "terminal_utility",'''
insert='''        # Accept cost-free schema v2, normalize to v1 validation layout.
        # Compatibility fields are internal placeholders, NEVER decision weights.
        if isinstance(artifact, dict) and artifact.get('schema_version') == 2:
            if 'cost_weights' in artifact or any('cost' in a for a in artifact.get('actions', [])):
                raise ValueError('VoI v2 must not contain costs')
            artifact['schema_version'] = 1
            artifact['cost_weights'] = {'money': 0, 'minutes': 0, 'tokens': 0}
            for action in artifact.get('actions', []):
                action['cost'] = {'money': 0, 'minutes': 0, 'tokens': 0}
            artifact.setdefault('provenance', {})['cost_free_schema_source'] = 2
'''
# Avoid duplicate normalization blocks on repeated application.
if "cost_free_schema_source" not in model:
    model = once(model, marker, insert+marker, 'v2 schema normalization')
elif model.count("cost_free_schema_source") != 1:
    raise RuntimeError('Unexpected repeated VoI v2 normalization; no files changed.')
ast.parse(model)

# Stage then back up and write only after BOTH source transforms succeed.
updates={IV:source, IO:model}
for path, updated in updates.items():
    backup=path.with_suffix(path.suffix+'.before_voi_v2.bak')
    if not backup.exists():
        shutil.copy2(path,backup)
    path.write_text(updated,encoding='utf-8')
    print('Updated:', path)
print('VoI v2 integration generated. Run regression tests; no tests were silently changed.')
