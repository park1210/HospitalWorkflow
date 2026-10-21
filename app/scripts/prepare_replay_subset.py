"""Freeze a deterministic patient subset of an existing held-out replay study."""
import argparse
from collections import defaultdict, Counter
import hashlib
import json
from pathlib import Path

from app.core.longitudinal_memory import visit_identity
from app.core.memory_evaluation import visit_key


def select_cases(cases, departments, count, seed):
    if type(count) is not int or not 1 <= count <= len(cases):
        raise ValueError('count must be within available held-out cases')
    identities = [visit_identity(c) for c in cases]
    if len({i['patient_id'] for i in identities}) != len(cases):
        raise ValueError('Subset requires one held-out encounter per patient')
    groups = defaultdict(list)
    for case, identity in zip(cases, identities):
        group = tuple(sorted(departments.get(visit_key(identity), [])))
        groups[group].append(case)
    for group in groups.values():
        group.sort(key=lambda c: hashlib.sha256((str(seed) + ':' + visit_identity(c)['patient_id']).encode()).hexdigest())
    selected = []
    while len(selected) < count:
        for key in sorted(groups):
            if groups[key] and len(selected) < count:
                selected.append(groups[key].pop(0))
    return selected


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--study-dir', type=Path, default=Path('outputs/action_replay_study_v2'))
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--count', type=int, default=15)
    p.add_argument('--seed', type=int, default=0)
    args = p.parse_args()
    if args.output_dir.exists():
        raise ValueError('Choose a new output directory')
    source = args.study_dir.resolve()
    read = lambda path: json.loads(path.read_text(encoding='utf-8'))
    plan = read(source/'plan.json')
    paths = {k: (source/v).resolve() for k, v in plan['inputs'].items()}
    cases = read(paths['cases'])
    departments = read(paths['gold_departments'])
    selected = select_cases(cases, departments, args.count, args.seed)
    keys = {visit_key(visit_identity(c)) for c in selected}
    patients = {visit_identity(c)['patient_id'] for c in selected}
    model = read(paths['voi_model'])
    if patients & set(model['provenance'].get('training_patients', [])):
        raise ValueError('Training/evaluation overlap')
    artifacts = {'cases': selected, 'memory': {'schema_version': 1,
        'records': [r for r in read(paths['memory'])['records'] if r['patient_id'] in patients]}}
    for name in ('labels', 'gold_departments', 'annotations'):
        if name in paths:
            artifacts[name] = {k: v for k, v in read(paths[name]).items() if k in keys}
    if 'scenarios' in paths:
        artifacts['scenarios'] = [r for r in read(paths['scenarios']) if visit_key(r) in keys]
    if plan['retrieved_mode'] != 'selective':
        raise ValueError('This replay subset command supports the existing lexical study only')
    plan['inputs'] = {k: str(v) for k, v in paths.items()}
    for name in artifacts:
        plan['inputs'][name] = name + '.json'
    plan['inputs']['routing_utility'] = 'fitted/routing_utility.json'
    report = {'source_study': str(source), 'source_cases_sha256': hashlib.sha256(paths['cases'].read_bytes()).hexdigest(),
        'count': len(selected), 'seed': args.seed, 'selection': 'department_round_robin_then_seeded_patient_hash',
        'patient_ids': sorted(patients), 'visit_keys': sorted(keys),
        'departments': dict(Counter(d for k in keys for d in departments[k])),
        'training_unchanged': True, 'conditions': ['B0', 'B1', 'B2', 'B3', 'B4']}
    plan['evaluation_subset'] = report
    artifacts.update(plan=plan, subset_report=report)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    for name, value in artifacts.items():
        (args.output_dir/(name+'.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    # Collection remains independent of which held-out patients are evaluated.
    (args.output_dir/'routing_probes.json').write_bytes((source/'routing_probes.json').read_bytes())
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
