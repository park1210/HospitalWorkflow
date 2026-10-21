"""Actual scheduler integration with deterministic agents, not clinical validation."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

from app.core.agent_registry import AgentRegistry
from app.core.diagnostic_belief import validation_utility
from app.core.information_value import InformationPolicy
from app.core.longitudinal_runner import run_longitudinal
from app.core.routing_utility import fit_utility
from test_encounter_pipeline import inputs, ScriptedSpecialist


def fixture(horizon):
    cases, registry = inputs()
    case = deepcopy(cases[0])
    diagnoses = ['D0', 'D1', 'D2', 'D3']
    model = {'schema_version': 2, 'model_id': 'step1-categorical', 'revision': '1',
             'provenance': {'synthetic': True, 'review_status': 'unreviewed',
                            'assumptions': ['Independent categorical observations conditional on diagnosis'],
                            'utility_scope': 'algorithm_validation_only'},
             'diagnoses': {d: 'neurology' for d in diagnoses},
             'prior': {d: .25 for d in diagnoses},
             'terminal_utility': validation_utility(diagnoses), 'horizon': horizon, 'actions': []}
    # A is best immediately (.7); B+C jointly identify all four states (1.0).
    tables = {'A_screen': [[.7 if i == j else .1 for i in range(4)] for j in range(4)],
              'B_axis': [[1, 1, 0, 0], [0, 0, 1, 1]],
              'C_axis': [[1, 0, 1, 0], [0, 1, 0, 1]]}
    case['current_encounter_events'] = []
    case['resource_profile'] = {'test_resources': {}, 'test_occupancy': {}, 'test_turnaround': {}}
    for name, rows in tables.items():
        outcomes = [{'id': str(i), 'likelihood': dict(zip(diagnoses, row)),
                     'observation': {'source': 'objective_findings', 'text': name + ': outcome ' + str(i)},
                     'supports_diagnoses': [d for d, p in zip(diagnoses, row) if p > 0]}
                    for i, row in enumerate(rows)]
        model['actions'].append({'id': name, 'type': 'request_test', 'target': name, 'outcomes': outcomes})
        case['current_encounter_events'].append({'event_id': name, 'action': 'Test', 'target': name,
                                               'available_minute': 0, 'evidence': 'outcome 0'})
        for field, value in [('test_resources', 'lab_slot'), ('test_occupancy', 1), ('test_turnaround', 1)]:
            case['resource_profile'][field][name] = value
    return case, registry, model


def run(case, registry, model=None, **kwargs):
    client = ScriptedSpecialist()
    report = run_longitudinal([case], registry_manifest=registry, client=client,
                              minute_limit=120, voi_model=model,
                              action_selector='bayesian_voi' if model else None, **kwargs)
    runtime = next(iter(report['visits'][0]['final_state']['cases'].values()))
    return report, runtime, client


class ResearchStep1RunnerTests(unittest.TestCase):
    def test_horizon_changes_executed_first_action_and_replans(self):
        first = {}
        for horizon in (1, 2, 3):
            case, registry, model = fixture(horizon)
            report, rt, client = run(case, registry, model)
            self.assertEqual(report['status'], 'completed')
            history = rt['voi_state']['history']
            first[horizon] = history[0]['target']
            self.assertEqual(history[0]['belief'], model['prior'])
            self.assertTrue(all(h['horizon'] == horizon for h in history))
            self.assertEqual(history[-1]['selected_action'], 'diagnose')
            self.assertEqual(history[-1]['target'], 'D0')
            self.assertNotEqual(history[1]['belief'], history[0]['belief'])
            consumed = set()
            for h in history:
                self.assertTrue(consumed.isdisjoint(c['action_id'] for c in h['candidates']))
                if h.get('action_id'):
                    consumed.add(h['action_id'])
            calls = [c for c in rt['llm_audit'] if c['role'] != 'patient']
            self.assertEqual(calls[0]['decision']['target'], first[horizon])
            self.assertEqual(calls[0]['routing']['executing_agent']['department'], 'neurology')
            self.assertGreater(history[1]['minute'], history[0]['minute'])
            # Neither hidden realized outcomes nor future evidence enter the initial prompt.
            self.assertEqual(client.payloads[0][1]['observation']['objective_findings'], [])
        self.assertEqual(first[1], 'A_screen')
        self.assertEqual(first[2], 'B_axis')
        # All first actions can attain utility 1 at H3; floating-point ties
        # do not change that optimum, so no unique first action is asserted.
        self.assertIn(first[3], {'A_screen', 'B_axis', 'C_axis'})

    def test_adaptive_primary_binding_and_abstention(self):
        case, manifest, _ = fixture(1)
        registry = AgentRegistry(manifest)
        observation = {'chief_complaint': case['current_initial_state']['doctor_visible_info']['chief_complaint']}
        rows = [{'split': 'train', 'patient_id': 'independent-training-patient', 'decision_id': 'train-1',
                 'agent_id': a['agent_id'], 'correct': a['department'] == 'pulmonology',
                 'observation': observation}
                for a in manifest['agents'] if a['role'] == 'specialty']
        artifact = fit_utility(rows, registry, min_samples=1)
        report, rt, client = run(case, manifest, primary_router='adaptive', routing_utility=artifact)
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(rt['voi_state']['initial_primary_routing']['selected_specialty'], 'pulmonology')
        self.assertEqual(client.payloads[0][1]['department'], 'pulmonology')
        self.assertEqual(client.payloads[0][0], registry.get('specialty', 'pulmonology')['model'])
        _, rt, client = run(case, manifest, primary_router='adaptive')
        self.assertEqual(rt['voi_state']['initial_primary_routing']['decision_status'], 'abstained')
        self.assertEqual(client.payloads[0][1]['role'], 'er')

    def test_unreleased_and_absent_questions_excluded(self):
        case, _, model = fixture(2)
        for a in model['actions']:
            a['type'] = 'ask_patient'
            a['target'] += '?'
            for outcome in a['outcomes']:
                outcome['observation']['source'] = 'history'
                outcome['supports_diagnoses'] = []
        case['current_encounter_events'] = [{'event_id': 'later', 'action': 'Ask', 'target': 'A_screen?',
                                            'available_minute': 100, 'evidence': 'outcome 0'}]
        runtime = SimpleNamespace(case_data=case, voi_state={}, current_time_min=0,
                                  question_history=[], voi_memory_pool={})
        policy = InformationPolicy(model)
        proposal = policy.propose(runtime, {}, actions=['ask_patient', 'diagnose'], tests=[],
                                  departments=[], evidence_records=[], allow_unresolved=True)
        self.assertEqual(proposal['action'], 'diagnose')
        self.assertEqual(proposal['certainty'], 'unresolved')
        self.assertEqual(len(runtime.voi_state['history'][0]['candidates']), 1)
        self.assertIsNone(policy.propose(runtime, {}, actions=['diagnose'], tests=[],
                                        departments=[], evidence_records=[], allow_unresolved=False))

    def test_memory_top_k_temporal_filter_and_supersession_reach_agent(self):
        case, registry, _ = fixture(1)
        old = case['past_visits'][0]['records'][0]
        replacement = {**deepcopy(old), 'memory_id': 'replacement', 'supersedes': [old['memory_id']],
                       'available_at': '2026-01-02T00:00:00Z'}
        other = {**deepcopy(old), 'memory_id': 'other', 'text': 'sensory'}
        future = {**deepcopy(old), 'memory_id': 'future', 'available_at': '2027-01-01T00:00:00Z'}
        report, rt, client = run(case, registry, mode='selective', top_k=1,
                                 initial_memory=[old, replacement, other, future], memory_source='fixed')
        self.assertEqual(report['status'], 'completed')
        records = client.payloads[0][1]['observation']['longitudinal_memory']['records']
        self.assertEqual([r['memory_id'] for r in records], ['replacement'])
        self.assertEqual(rt['llm_audit'][0]['memory_context']['records'], records)

    def test_hidden_realization_does_not_change_initial_plan(self):
        case, registry, model = fixture(2)
        _, rt1, _ = run(case, registry, model)
        changed = deepcopy(case)
        for event in changed['current_encounter_events']:
            event['evidence'] = 'outcome 1'
        _, rt2, _ = run(changed, registry, model)
        self.assertEqual(rt1['voi_state']['history'][0]['candidates'],
                         rt2['voi_state']['history'][0]['candidates'])
        self.assertEqual(rt1['voi_state']['history'][0]['target'], rt2['voi_state']['history'][0]['target'])
        self.assertNotEqual(rt1['voi_state']['history'][1]['belief'], rt2['voi_state']['history'][1]['belief'])


if __name__ == '__main__':
    unittest.main()
