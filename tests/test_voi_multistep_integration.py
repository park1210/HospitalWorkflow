"""Cost-free VoI regression checks for HospitalWorkflow.
Copy this file to tests/test_voi_multistep_integration.py.
"""
import json
from pathlib import Path
import unittest
from copy import deepcopy

from app.core.information_value import action_values, select_action
from app.core.voi_planning import plan_voi

ROOT = Path(__file__).resolve().parents[1]


def model():
    return json.loads((ROOT / 'app/data/voi_synthetic/model.json').read_text(encoding='utf-8'))


class CostFreeMultiStepIntegrationTests(unittest.TestCase):
    def test_cost_fields_have_no_effect_on_selection(self):
        artifact = model()
        candidates = [
            {'action_id': a['id'], 'type': {'request_test':'Test','ask_patient':'Ask',
             'consult_specialty':'Consult','retrieve_memory':'Memory'}[a['type']],
             'action': a['type'], 'target': a['target'], 'outcome_model': a['id']}
            for a in artifact['actions']
        ] + [{'action_id': 'diagnose', 'type':'Diagnose', 'action':'diagnose',
              'target': None, 'outcome_model':None}]
        baseline = select_action(candidates, selector='bayesian_voi',
                                 belief=artifact['prior'], artifact=artifact)
        altered = deepcopy(artifact)
        altered['cost_weights'] = {'money': 100000, 'minutes': 100000, 'tokens': 100000}
        for a in altered['actions']:
            a['cost'] = {'money': 100000, 'minutes': 100000, 'tokens': 100000}
        changed = select_action(candidates, selector='bayesian_voi',
                                belief=altered['prior'], artifact=altered)
        self.assertEqual(baseline['selected_action']['action_id'],changed['selected_action']['action_id'])
        self.assertEqual([x['q_value'] for x in baseline['values']],
                         [x['q_value'] for x in changed['values']])
        self.assertEqual(changed['cost_model'], 'none')

    def test_horizon_is_passed_to_actual_selector(self):
        artifact = model()
        artifact['horizon'] = 3
        candidates = [
            {'action_id': a['id'], 'type': 'Test', 'outcome_model': a['id'],
             'action': a['type'], 'target': a['target']} for a in artifact['actions']
        ] + [{'action_id':'diagnose','type':'Diagnose','outcome_model':None,
              'action':'diagnose','target':None}]
        answer = select_action(candidates, selector='bayesian_voi',
                               belief=artifact['prior'], artifact=artifact)
        self.assertEqual(answer['horizon'], 3)
        expected = plan_voi(artifact['prior'],artifact['actions'],artifact['terminal_utility'],horizon=3)
        self.assertAlmostEqual(answer['values'][0]['q_value'], expected['optimal_value'])

    def test_one_step_values_do_not_include_cost(self):
        artifact=model()
        scores=action_values(artifact['prior'],artifact['actions'],artifact)
        self.assertTrue(scores)
        self.assertTrue(all(row['cost_penalty']==0 for row in scores))
        baseline=max(artifact['prior'].values())
        self.assertAlmostEqual(scores[0]['voi'],scores[0]['q_value']-baseline)


if __name__=='__main__':
    unittest.main()
