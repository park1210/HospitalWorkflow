"""Explicit fictional control experiment; never modifies real/source replay data."""
import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import random

from app.core.agent_registry import AgentRegistry
from app.core.routing_utility import fit_utility
from app.core.information_outcomes import InformationOutcomes
from app.core.diagnostic_belief import validation_utility


def build(manifest, *, reliability=.85, seed=42):
    if type(reliability) not in (int, float) or not math.isfinite(reliability) or not .2 < reliability < 1:
        raise ValueError('Assumed assay reliability must be between .2 and 1')
    departments = ['cardiology', 'endocrinology', 'nephrology', 'neurology', 'pulmonology']
    registry = deepcopy(manifest)
    registry['agents'] = [a for a in registry['agents'] if a['role'] == 'er' or a['department'] in departments]
    bound = AgentRegistry(registry)
    if {a['department'] for a in registry['agents'] if a['role'] == 'specialty'} != set(departments):
        raise ValueError('All five fictional-control department bindings required')
    diagnoses = {'Simulation condition ' + str(i+1): dept for i, dept in enumerate(departments)}
    names = list(diagnoses)
    def observation(index):
        return {'chief_complaint': 'Fictional presentation channel_' + str(index+1)}
    rows = []
    for index, dept in enumerate(departments):
        for repeat in range(3):
            for agent in registry['agents']:
                if agent['role'] == 'specialty':
                    rows.append({'split': 'train', 'patient_id': 'hypothetical-train-' + str(index),
                        'decision_id': str(repeat), 'agent_id': agent['agent_id'],
                        'observation': observation(index), 'correct': agent['department'] == dept})
    routing = fit_utility(rows, bound)
    routing['provenance'] = {'synthetic': True, 'outcomes': 'ASSUMED_NOT_LLM_MEASURED',
        'assumption': 'Matching fictional presentation channel implies specialist success; others fail'}
    target = 'Fictional classification assay'
    model = {'schema_version': 2, 'model_id': 'HYPOTHETICAL_ONLY_classification', 'revision': '1',
        'provenance': {'synthetic': True, 'review_status': 'unreviewed',
            'assumptions': ['Entire population and assay are invented for algorithm verification',
                'Assay reliability is user-configurable, not estimated from medical data',
                'Fictional outcome supports only its associated fictional diagnosis'],
            'utility_scope': 'algorithm_validation_only', 'assumed_reliability': reliability},
        'diagnoses': diagnoses, 'prior': {d: .2 for d in names},
        'terminal_utility': validation_utility(names), 'horizon': 2,
        'actions': [{'id': 'fictional-assay', 'type': 'request_test', 'target': target,
            'outcomes': [{'id': 'category-' + str(i+1),
                'likelihood': {d: reliability if d == diagnosis else (1-reliability)/4 for d in names},
                'observation': {'source': 'objective_findings', 'text': target + ': Fictional evidence supports ' + diagnosis},
                'supports_diagnoses': [diagnosis]} for i, diagnosis in enumerate(names)]}]}
    InformationOutcomes(model)
    rng = random.Random(seed)
    cases, labels, gold, memory = [], {}, {}, []
    generated_matches = 0
    for i in range(15):
        index = i % 5
        diagnosis = names[index]
        patient = 'hypothetical-evaluation-' + str(i+1)
        probabilities = [reliability if d == diagnosis else (1-reliability)/4 for d in names]
        result = rng.choices(names, weights=probabilities)[0]
        generated_matches += int(result == diagnosis)
        record = {'memory_id': patient+'-history', 'patient_id': patient, 'visit_id': 'v0',
            'visit_started_at': '2025-01-01T00:00:00Z', 'observed_at': '2025-01-01T00:00:00Z',
            'available_at': '2025-01-01T00:00:00Z', 'source_id': 'HYPOTHETICAL_ONLY', 'kind': 'history',
            'text': observation(index)['chief_complaint'] + ' was previously recorded.', 'supersedes': []}
        memory.append(record)
        cases.append({'case_id': patient, 'longitudinal': {'patient_id': patient, 'visit_id': 'v1',
                     'started_at': '2026-01-01T00:00:00Z'},
            'index_encounter_id': 'v1', 'index_encounter_start': '2026-01-01T00:00:00Z',
            'past_visits': [{'visit_id': 'v0', 'started_at': '2025-01-01T00:00:00Z', 'records': [record]}],
            'current_initial_state': {'doctor_visible_info': observation(index), 'patient_visible_info': {}},
            'current_encounter_events': [{'event_id': patient+'-result', 'action': 'Test', 'target': target,
                'available_minute': 0, 'evidence': 'Fictional evidence supports ' + result}]})
        key = json.dumps([patient, 'v1'], ensure_ascii=False)
        labels[key], gold[key] = [diagnosis], [departments[index]]
    return {'cases': cases, 'labels': labels, 'gold_departments': gold, 'registry': registry,
        'memory': {'schema_version': 1, 'records': memory}, 'routing_utility': routing, 'voi_model': model,
        'prices': {}, 'assumptions': {'scope': 'HYPOTHETICAL_ONLY_NOT_CLINICAL_PERFORMANCE', 'seed': seed,
            'assumed_reliability': reliability, 'generated_assay_matches': generated_matches, 'cases': 15,
            'warning': 'Generated assay match count is not LLM accuracy. No samples were retried to hit a target.'}}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--registry', type=Path, default=Path('app/data/synthea_v2/registry_shared_qwen.json'))
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--assumed-reliability', type=float, default=.85)
    p.add_argument('--seed', type=int, default=42)
    args = p.parse_args()
    if args.output_dir.exists():
        raise ValueError('Choose a new output directory')
    artifacts = build(json.loads(args.registry.read_text(encoding='utf-8')),
                      reliability=args.assumed_reliability, seed=args.seed)
    plan = {'schema_version': 1, 'repeats': 1, 'retrieved_mode': 'selective', 'top_k': 5,
        'minute_limit': 120, 'max_memory_chars': 30000, 'provenance': artifacts['assumptions'],
        'inputs': {k: k+'.json' for k in artifacts if k != 'assumptions'}}
    artifacts['plan'] = plan
    args.output_dir.mkdir(parents=True, exist_ok=False)
    for name, value in artifacts.items():
        (args.output_dir/(name+'.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(artifacts['assumptions']))


if __name__ == '__main__':
    main()
