from copy import deepcopy
import json
from pathlib import Path
import unittest

from app.scripts.prepare_feature_benchmark import build, GROUPS, DIAGNOSES
from app.core.clinical_observation import prepare_encounter, memory_query
from app.core.longitudinal_memory import PatientMemoryStore, visit_identity
from app.core.longitudinal_runner import run_longitudinal
from app.core.memory_evaluation import visit_key
from test_encounter_pipeline import ScriptedSpecialist


class FeatureBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(Path('app/data/synthea_v2/registry_shared_qwen.json').read_text(encoding='utf-8'))
        cls.data = build(cls.manifest)

    def case(self, group):
        return next(c for c in self.data['cases'] if '-'+group+'-' in c['case_id'])

    def run_case(self, group, horizon=2, mode='selective'):
        model = deepcopy(self.data['voi_model'])
        model['horizon'] = horizon
        result = run_longitudinal([self.case(group)], client=ScriptedSpecialist(),
            registry_manifest=self.data['registry'], routing_mode='er_only', mode=mode, top_k=1,
            voi_model=model, minute_limit=120, diagnosis_catalog=DIAGNOSES,
            diagnosis_departments=model['diagnoses'])
        self.assertEqual(result['status'], 'completed')
        return next(iter(result['visits'][0]['final_state']['cases'].values()))

    def test_predefined_groups_and_disjoint_patient_sets(self):
        self.assertEqual(self.data, build(self.manifest))
        self.assertEqual(self.data['design']['groups'], {g: 3 for g in GROUPS})
        evaluation = {c['longitudinal']['patient_id'] for c in self.data['cases']}
        training = {p['patient_id'] for p in self.data['routing_probes']}
        self.assertFalse(evaluation & training)
        self.assertNotIn('routing_utility', self.data)
        for c in self.data['cases']:
            prepare_encounter(c)
            self.assertNotIn('diagnosis', c['current_initial_state'])
        for probe in self.data['routing_probes']:
            self.assertNotIn('expected_diagnoses', probe['observation'])

    def test_selective_memory_keeps_relevant_excludes_superseded(self):
        case = self.case('retrieval')
        identity = visit_identity(case)
        store = PatientMemoryStore([r for v in case['past_visits'] for r in v['records']])
        query = memory_query({'chief_complaint': case['current_initial_state']['doctor_visible_info']['chief_complaint']})
        selected = store.retrieve(identity, query, 'selective', 1)['records']
        self.assertEqual([r['memory_id'] for r in selected], self.data['annotations'][visit_key(identity)]['relevant_memory_ids'])
        self.assertGreater(len(store.retrieve(identity, query, 'full_history', 1)['records']), 20)

    def test_memory_reduces_needed_information_actions_in_same_policy(self):
        with_memory = self.run_case('memory')
        no_memory = self.run_case('memory', mode='none')
        self.assertLess(len(with_memory['voi_state']['history']), len(no_memory['voi_state']['history']))
        self.assertEqual(with_memory['voi_state']['history'][-1]['target'], no_memory['voi_state']['history'][-1]['target'])

    def test_horizon_changes_first_action_without_changing_case(self):
        h1 = self.run_case('voi', horizon=1)
        h2 = self.run_case('voi', horizon=2)
        self.assertEqual(h1['voi_state']['history'][0]['action_id'], 'screen')
        self.assertIn(h2['voi_state']['history'][0]['action_id'], {'axis', 'subgroup'})
        self.assertNotEqual(h1['voi_state']['history'][0]['action_id'], h2['voi_state']['history'][0]['action_id'])

    def test_control_does_not_add_useless_action(self):
        state = self.run_case('control')
        decisions = state['voi_state']['history']
        self.assertEqual([d['selected_action'] for d in decisions], ['request_test', 'diagnose'])
        self.assertEqual(decisions[0]['action_id'], 'confirm')


if __name__ == '__main__':
    unittest.main()
