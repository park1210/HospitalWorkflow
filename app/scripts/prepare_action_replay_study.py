"""Prepare an explicitly restricted, patient-disjoint exploratory replay study.

No LLM calls. Does not manufacture specialty correctness or clinical support.
Original input files are never changed. All conditions use the same action menu.
"""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from statistics import median

from app.core.clinical_observation import memory_query, initial_symptoms
from app.core.longitudinal_memory import PatientMemoryStore
from app.core.memory_evaluation import visit_key
from app.core.diagnostic_belief import validation_utility
from app.core.voi_evaluation import fit_outcome_spec
from app.core.agent_registry import AgentRegistry


def numeric_event(event):
    """Only unambiguous numeric source facts; no clinical cutoffs inferred."""
    raw = json.loads(event['evidence'])
    if event['action'] == 'Ask':
        records = raw.get('facts', [])
        pairs = [(r['code'], r.get('units'), r.get('value')) for r in records]
    elif event['action'] == 'Test':
        records = raw.get('records', [])
        pairs = [(r['code'], r['recorded_evidence'].get('units'), r['recorded_evidence'].get('value'))
                 for r in records if r['event_type'] == 'observations']
    else:
        return None
    if len(pairs) != 1:
        return None
    code, unit, value = pairs[0]
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    key = json.dumps([event['action'], code, unit], ensure_ascii=False)
    return key, number


def prepare(cases, labels, departments, manifest, *, seed=0, horizon=2, max_actions=6):
    if type(max_actions) is not int or not 1 <= max_actions <= 12:
        raise ValueError('max_actions must be 1..12')
    AgentRegistry(manifest)
    excluded, groups, values, by_patient = [], defaultdict(list), {}, {}
    for case in cases:
        identity = {'patient_id': case['longitudinal']['patient_id'], 'visit_id': case['index_encounter_id']}
        key = visit_key(identity)
        patient = identity['patient_id']
        if patient in by_patient:
            raise ValueError('This adapter requires one encounter per patient')
        by_patient[patient] = case
        diagnoses, depts = labels.get(key, []), departments.get(key, [])
        if len(diagnoses) != 1 or len(depts) != 1:
            excluded.append({'case_id': case['case_id'], 'reason': 'ambiguous_or_missing_source_label'})
            continue
        event_values = {}
        for event in case['current_encounter_events']:
            parsed = numeric_event(event)
            if parsed:
                code, number = parsed
                if code in event_values:
                    raise ValueError('Duplicate numeric action/unit within encounter')
                event_values[code] = (number, event)
        if not any(json.loads(code)[0] == 'Test' for code in event_values):
            excluded.append({'case_id': case['case_id'], 'reason': 'no_unambiguous_numeric_test'})
            continue
        values[patient] = event_values
        groups[diagnoses[0]].append((patient, depts[0]))
    train, test, taxonomy = [], [], {}
    for diagnosis, entries in sorted(groups.items()):
        if len(entries) < 2 or len({dept for _, dept in entries}) != 1:
            excluded.extend({'case_id': by_patient[p]['case_id'], 'reason': 'insufficient_or_conflicting_label_group'}
                            for p, _ in entries)
            continue
        taxonomy[diagnosis] = entries[0][1]
        entries.sort(key=lambda row: hashlib.sha256((str(seed) + ':' + row[0]).encode()).hexdigest())
        n_test = max(1, int(len(entries) * .3))
        test.extend((p, diagnosis) for p, _ in entries[:n_test])
        train.extend((p, diagnosis) for p, _ in entries[n_test:])
    if len(taxonomy) < 2:
        raise ValueError('Need at least two labels with disjoint train/test patients')
    # Only TRAIN determines the common action menu, thresholds, and likelihoods.
    coverage = Counter(code for patient, _ in train for code in values[patient])
    supported = [code for code in coverage if all(any(code in values[p] for p, d in train if d == diagnosis)
                                                for diagnosis in taxonomy)]
    supported.sort(key=lambda code: (-coverage[code], code))
    selected = supported[:max_actions]
    if not selected:
        raise ValueError('No action has observed training support for every diagnosis')
    thresholds = {code: median(values[p][code][0] for p, _ in train if code in values[p]) for code in selected}
    action_ids = {code: 'replay-' + hashlib.sha256(code.encode()).hexdigest()[:16] for code in selected}
    targets = {}
    for code in selected:
        event = next(values[p][code][1] for p, _ in train if code in values[p])
        targets[code] = event['target'] if event['action'] == 'Ask' else 'Source test ' + code
    actions = []
    for code in selected:
        kind = json.loads(code)[0]
        actions.append({'id': action_ids[code], 'type': 'ask_patient' if kind == 'Ask' else 'request_test',
            'target': targets[code], 'outcomes': [{'id': bin_id,
                'observation': {'source': 'history' if kind == 'Ask' else 'objective_findings',
                                'text': targets[code] + ': ' + bin_id},
                'supports_diagnoses': []} for bin_id in ('at_or_below_train_median', 'above_train_median')]})
    spec = {'model_id': 'action-replay-exploratory', 'revision': '1',
        'provenance': {'synthetic': True, 'review_status': 'unreviewed',
            'assumptions': ['Source-observed labels, not clinical gold', 'Latest-within-index snapshot replay',
                'Train-only median bins are statistical, not clinical thresholds',
                'Conditional independence of action outcomes is assumed'],
            'utility_scope': 'algorithm_validation_only', 'observation_encoding': 'replay_bins_v1',
            'binning_thresholds': thresholds, 'clinical_support': 'not_inferred'},
        'diagnoses': taxonomy, 'terminal_utility': validation_utility(taxonomy), 'horizon': horizon, 'actions': actions}
    def outcome(number, code):
        return 'at_or_below_train_median' if number <= thresholds[code] else 'above_train_median'
    rows = [{'patient_id': p, 'visit_id': by_patient[p]['index_encounter_id'], 'split': 'train',
             'diagnosis': d, 'action_id': action_ids[code], 'outcome_id': outcome(values[p][code][0], code)}
            for p, d in train for code in selected if code in values[p]]
    model = fit_outcome_spec(spec, rows, evaluation_patients=[p for p, _ in test])
    transformed = {}
    for patient, _ in train + test:
        case = deepcopy(by_patient[patient])
        case['longitudinal'] = {'patient_id': patient, 'visit_id': case['index_encounter_id'],
                                'started_at': case['index_encounter_start']}
        events = []
        for code in selected:
            if code not in values[patient]:
                continue
            number, original = values[patient][code]
            event = deepcopy(original)
            event['target'] = targets[code]
            event['evidence'] = json.dumps({'replay_bin': outcome(number, code),
                'source_evidence': json.loads(original['evidence'])}, ensure_ascii=False)
            events.append(event)
        case['current_encounter_events'] = events
        transformed[patient] = case
    # Same shared models, restricted to the declared study's department universe.
    registry = deepcopy(manifest)
    registry['agents'] = [a for a in registry['agents'] if a['role'] == 'er' or a['department'] in set(taxonomy.values())]
    AgentRegistry(registry)
    records = {r['memory_id']: r for p, _ in test for v in transformed[p]['past_visits'] for r in v['records']}
    probes = []
    for patient, _ in train:
        case = transformed[patient]
        identity = {'patient_id': patient, 'visit_id': case['index_encounter_id'], 'started_at': case['index_encounter_start']}
        initial = case['current_initial_state']
        observed = {'chief_complaint': initial['doctor_visible_info'].get('chief_complaint', ''),
            'current_symptoms': initial_symptoms(initial), 'objective_findings': [], 'history': []}
        store = PatientMemoryStore([r for v in case['past_visits'] for r in v['records']])
        observed['longitudinal_memory'] = store.retrieve(identity, memory_query(observed), 'selective', 5, max_chars=30000)
        probes.append({'patient_id': patient, 'decision_id': case['index_encounter_id'] + ':initial',
            'split': 'train', 'observation': observed, 'expected_diagnoses': labels[visit_key(identity)],
            'diagnosis_catalog': sorted(taxonomy) + ['Unresolved']})
    eval_cases = [transformed[p] for p, _ in test]
    eval_keys = {visit_key({'patient_id': p, 'visit_id': by_patient[p]['index_encounter_id']}) for p, _ in test}
    return {'cases': eval_cases, 'labels': {k: labels[k] for k in eval_keys},
        'gold_departments': {k: departments[k] for k in eval_keys}, 'memory': {'schema_version': 1, 'records': list(records.values())},
        'registry': registry, 'voi_model': model, 'routing_probes': probes, 'voi_spec': spec, 'voi_training_rows': rows,
        'prices': {}, 'study_report': {'seed': seed, 'train_patients': [p for p, _ in train],
            'test_patients': [p for p, _ in test], 'excluded': excluded, 'selected_actions': selected,
            'training_action_coverage': dict(coverage), 'baseline': 'ER-only',
            'all_conditions_share_restricted_actions': True, 'clinical_diagnosis_support': 'not_annotated',
            'routing_calls_planned': len(probes) * (len(registry['agents']) - 1)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path('action_replay_100_v1'))
    parser.add_argument('--registry', type=Path, default=Path('app/data/synthea_v2/registry_shared_qwen.json'))
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--horizon', type=int, choices=[1, 2, 3], default=2)
    parser.add_argument('--max-actions', type=int, default=6)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError('Choose a new output directory')
    read = lambda path: json.loads(path.read_text(encoding='utf-8'))
    result = prepare(read(args.data_dir/'cases.json'), read(args.data_dir/'labels_observed.json'),
        read(args.data_dir/'departments_source_policy.json'), read(args.registry),
        seed=args.seed, horizon=args.horizon, max_actions=args.max_actions)
    result['study_report']['input_sha256'] = {name: hashlib.sha256((args.data_dir/name).read_bytes()).hexdigest()
        for name in ('cases.json', 'labels_observed.json', 'departments_source_policy.json')}
    result['study_report']['registry_sha256'] = hashlib.sha256(args.registry.read_bytes()).hexdigest()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    for name, value in result.items():
        (args.output_dir/(name+'.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    plan = {'schema_version': 1, 'repeats': 1, 'retrieved_mode': 'selective', 'top_k': 5, 'minute_limit': 120,
        'max_memory_chars': 30000, 'provenance': result['voi_model']['provenance'],
        'inputs': {name: name+'.json' for name in ('cases','labels','gold_departments','memory','registry','voi_model','prices')}}
    plan['inputs']['routing_utility'] = 'fitted/routing_utility.json'
    (args.output_dir/'plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: result['study_report'][k] for k in ('routing_calls_planned','selected_actions')}, ensure_ascii=False))
    print('Prepared; collect routing probes and fit utility before executing plan.json.')


if __name__ == '__main__':
    main()
