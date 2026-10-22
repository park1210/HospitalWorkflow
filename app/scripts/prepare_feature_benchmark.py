"""Predefined fictional mechanism benchmark, not a tuned clinical accuracy set.

Each condition receives identical cases and executable menus. Router performance
must be measured on separate training probes; no fabricated success artifact.
"""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random

from app.core.agent_registry import AgentRegistry
from app.core.clinical_observation import prepare_encounter, memory_query
from app.core.diagnostic_belief import validation_utility
from app.core.information_outcomes import InformationOutcomes
from app.core.longitudinal_memory import PatientMemoryStore, visit_identity
from app.core.memory_evaluation import visit_key

GROUPS = ('memory', 'retrieval', 'routing', 'voi', 'control')
DIAGNOSES = ['Fictional state A', 'Fictional state B', 'Fictional state C', 'Fictional state D']
DEPARTMENTS = ['cardiology', 'endocrinology', 'nephrology', 'neurology']
RULES = ('Fictional task, not medical diagnosis. State A=(subgroup 0, axis 0); '
         'B=(0,1); C=(1,0); D=(1,1). The subgroup is stable across visits. '
         'Use only current evidence and non-superseded historical subgroup records. '
         'A noisy screen can be wrong; unrelated noise is not diagnostic. ')


def outcome_model():
    actions = []
    def add(identifier, kind, target, probabilities, descriptions, support):
        source = {'request_test': 'objective_findings', 'ask_patient': 'history', 'retrieve_memory': 'memory'}[kind]
        actions.append({'id': identifier, 'type': kind, 'target': target, 'outcomes': [
            {'id': str(i), 'likelihood': dict(zip(DIAGNOSES, probabilities[i])),
             'observation': {'source': source, 'text': (target + ': ' if kind == 'request_test' else '') + text},
             'supports_diagnoses': support[i]} for i, text in enumerate(descriptions)]})
    subgroup = [[1, 1, 0, 0], [0, 0, 1, 1]]
    axis = [[1, 0, 1, 0], [0, 1, 0, 1]]
    add('memory', 'retrieve_memory', 'longitudinal', subgroup,
        ['Historical subgroup record: subgroup=0.', 'Historical subgroup record: subgroup=1.'], [[], []])
    add('ask', 'ask_patient', 'What is your stable subgroup?', subgroup,
        ['Reported subgroup=0.', 'Reported subgroup=1.'], [[], []])
    add('screen', 'request_test', 'Noisy screening assay (70 percent reliable)',
        [[.7 if i == j else .1 for i in range(4)] for j in range(4)],
        ['Screen suggests ' + d + '.' for d in DIAGNOSES], [[d] for d in DIAGNOSES])
    add('subgroup', 'request_test', 'Objective subgroup assay', subgroup,
        ['Confirmed subgroup=0.', 'Confirmed subgroup=1.'], [DIAGNOSES[:2], DIAGNOSES[2:]])
    add('axis', 'request_test', 'Objective axis assay', axis,
        ['Confirmed axis=0.', 'Confirmed axis=1.'], [DIAGNOSES[::2], DIAGNOSES[1::2]])
    add('noise', 'request_test', 'Unrelated noise assay', [[.5]*4, [.5]*4],
        ['Independent coin=0.', 'Independent coin=1.'], [[], []])
    add('confirm', 'request_test', 'Definitive fictional classification',
        [[int(i == j) for i in range(4)] for j in range(4)],
        ['Confirmed ' + d + '.' for d in DIAGNOSES], [[d] for d in DIAGNOSES])
    artifact = {'schema_version': 2, 'model_id': 'FICTIONAL_MECHANISM_BENCHMARK', 'revision': '1',
        'provenance': {'synthetic': True, 'review_status': 'unreviewed',
            'assumptions': ['Predefined fictional bit states, not clinical conditions',
                'Subgroup persists across visits', 'Declared synthetic outcome distributions',
                'One use per action; shared menus and budgets across all conditions'],
            'utility_scope': 'algorithm_validation_only'},
        'diagnoses': dict(zip(DIAGNOSES, DEPARTMENTS)), 'prior': {d: .25 for d in DIAGNOSES},
        'terminal_utility': validation_utility(DIAGNOSES), 'horizon': 2, 'actions': actions}
    InformationOutcomes(artifact)
    return artifact


def build(manifest, *, per_group=3, seed=42):
    if type(per_group) is not int or per_group < 1:
        raise ValueError('per_group must be positive')
    registry = deepcopy(manifest)
    registry['agents'] = [a for a in registry['agents'] if a['role'] == 'er' or a['department'] in DEPARTMENTS]
    AgentRegistry(registry)
    if {a['department'] for a in registry['agents'] if a['role'] == 'specialty'} != set(DEPARTMENTS):
        raise ValueError('Four department model bindings required')
    model = outcome_model()
    action_map = {a['id']: a for a in model['actions']}
    menus = {'memory': ['ask', 'axis', 'noise'], 'retrieval': ['ask', 'axis', 'noise'],
             'routing': ['screen', 'subgroup', 'axis', 'noise'],
             'voi': ['screen', 'subgroup', 'axis', 'noise'], 'control': ['confirm', 'noise']}
    cases, train_cases, labels, gold, scenarios, memory, annotations, probes = [], [], {}, {}, [], [], {}, []
    def make_case(group, index, split):
        patient = 'feature-' + split + '-' + group + '-' + str(index)
        # Separate streams: changing evaluation outcomes never changes training probes.
        rng = random.Random(int(hashlib.sha256((str(seed)+':'+patient).encode()).hexdigest(), 16))
        state = (index + GROUPS.index(group)) % 4
        doctor = {'chief_complaint': RULES + 'Presenting problem: subgroup and axis need assessment.'}
        records = []
        def record(identifier, text, available='2025-01-01T00:00:00Z', supersedes=None):
            return {'memory_id': patient+'-'+identifier, 'patient_id': patient, 'visit_id': 'v0',
                'visit_started_at': '2025-01-01T00:00:00Z', 'observed_at': available, 'available_at': available,
                'source_id': 'FICTIONAL_MECHANISM_BENCHMARK', 'kind': 'history',
                'text': text, 'supersedes': supersedes or []}
        relevant = []
        if group in {'memory', 'retrieval'}:
            if group == 'retrieval':
                records.append(record('old', 'Historical subgroup record: subgroup=' + str(1-state//2) + '.'))
            current = record('current', 'Historical subgroup record: subgroup=' + str(state//2) + '.',
                '2025-02-01T00:00:00Z', [patient+'-old'] if group == 'retrieval' else [])
            records.append(current)
            relevant.append(current['memory_id'])
            if group == 'retrieval':
                for n in range(24):
                    records.append(record('noise-'+str(n), 'Unrelated historical note: travel logistics and administrative scheduling ' + str(n),
                                          '2025-03-01T00:00:00Z'))
        events = []
        for identifier in menus[group]:
            action = action_map[identifier]
            outcome = rng.choices(action['outcomes'], weights=[o['likelihood'][DIAGNOSES[state]] for o in action['outcomes']])[0]
            text = outcome['observation']['text']
            if action['type'] == 'request_test':
                text = text[len(action['target'])+2:]
            events.append({'event_id': patient+'-'+identifier,
                'action': 'Test' if action['type'] == 'request_test' else 'Ask',
                'target': action['target'], 'available_minute': 0, 'evidence': text})
        rng.shuffle(events)
        case = {'case_id': patient, 'longitudinal': {'patient_id': patient, 'visit_id': 'v1', 'started_at': '2026-01-01T00:00:00Z'},
            'index_encounter_id': 'v1', 'index_encounter_start': '2026-01-01T00:00:00Z',
            'past_visits': [{'visit_id': 'v0', 'started_at': '2025-01-01T00:00:00Z', 'records': records}] if records else [],
            'current_initial_state': {'doctor_visible_info': doctor, 'patient_visible_info': {}},
            'current_encounter_events': events}
        prepare_encounter(case)
        return case, state, relevant
    for group in GROUPS:
        for index in range(per_group):
            case, state, relevant = make_case(group, index, 'evaluation')
            cases.append(case)
            identity = visit_identity(case)
            key = visit_key(identity)
            labels[key], gold[key] = [DIAGNOSES[state]], [DEPARTMENTS[state]]
            scenarios.append({**identity, 'group': group})
            records = [r for v in case['past_visits'] for r in v['records']]
            memory.extend(records)
            annotations[key] = {'relevant_memory_ids': relevant,
                                'stale_memory_ids': [r['memory_id'] for r in records if r['memory_id'].endswith('-old')]}
        for index in range(4):
            case, state, _ = make_case(group, index, 'train')
            train_cases.append(case)
            identity = visit_identity(case)
            # Probe two public decision states. No gold/result is added to initial state.
            records = [r for v in case['past_visits'] for r in v['records']]
            base = {'chief_complaint': case['current_initial_state']['doctor_visible_info']['chief_complaint'],
                    'current_symptoms': [], 'history': [], 'objective_findings': []}
            store = PatientMemoryStore(records)
            for phase in ('initial', 'after_observation'):
                observed = deepcopy(base)
                if phase == 'after_observation':
                    for e in case['current_encounter_events']:
                        if e['action'] == 'Test' and 'noise' not in e['target'].lower():
                            observed['objective_findings'].append(e['target'] + ': ' + e['evidence'])
                            break
                observed['longitudinal_memory'] = store.retrieve(identity, memory_query(observed), 'selective', 1)
                probes.append({'patient_id': identity['patient_id'], 'decision_id': identity['visit_id']+':'+phase,
                    'split': 'train', 'observation': observed, 'expected_diagnoses': [DIAGNOSES[state]],
                    'diagnosis_catalog': DIAGNOSES + ['Unresolved']})
    return {'cases': cases, 'training_cases': train_cases, 'labels': labels, 'gold_departments': gold,
        'scenarios': scenarios, 'annotations': annotations, 'memory': {'schema_version': 1, 'records': memory},
        'registry': registry, 'voi_model': model, 'routing_probes': probes, 'prices': {},
        'design': {'scope': 'FICTIONAL_MECHANISM_BENCHMARK_NOT_CLINICAL', 'seed': seed,
            'groups': dict(Counter(r['group'] for r in scenarios)), 'routing_calls_planned': len(probes)*4,
            'fixed_before_execution': True, 'rank_order_guaranteed': False,
            'routing_note': 'Same base model may have no specialty advantage. Measure it; ties abstain.',
            'control_note': 'A single definitive test suffices; initial diagnosis is not assumed supported.',
            'menus': menus}}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--registry', type=Path, default=Path('app/data/synthea_v2/registry_shared_qwen.json'))
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--per-group', type=int, default=3)
    p.add_argument('--seed', type=int, default=42)
    args = p.parse_args()
    if args.output_dir.exists():
        raise ValueError('Choose a new output directory')
    artifacts = build(json.loads(args.registry.read_text(encoding='utf-8')), per_group=args.per_group, seed=args.seed)
    plan = {'schema_version': 1, 'repeats': 1, 'retrieved_mode': 'selective', 'top_k': 1,
        'minute_limit': 120, 'max_memory_chars': 30000, 'provenance': artifacts['design'],
        'inputs': {k: k+'.json' for k in ('cases','labels','gold_departments','scenarios','annotations','memory','registry','voi_model','prices')}}
    plan['inputs']['routing_utility'] = 'fitted/routing_utility.json'
    artifacts['plan'] = plan
    h1 = deepcopy(artifacts['voi_model'])
    h1['horizon'] = 1
    artifacts['voi_model_h1'] = h1
    h1plan = deepcopy(plan)
    h1plan['inputs']['voi_model'] = 'voi_model_h1.json'
    artifacts['plan_h1'] = h1plan
    args.output_dir.mkdir(parents=True, exist_ok=False)
    for name, value in artifacts.items():
        (args.output_dir/(name+'.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(artifacts['design'], ensure_ascii=False))


if __name__ == '__main__':
    main()
