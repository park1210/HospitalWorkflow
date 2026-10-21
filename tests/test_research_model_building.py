"""Training contract checks; tiny categorical data, no live model calls."""
from copy import deepcopy
import unittest

from app.core.information_outcomes import InformationOutcomes
from app.core.voi_evaluation import fit_outcomes, fit_outcome_spec
from app.scripts.build_research_models import build_models
from test_research_step1_runner import fixture
from test_research_math_v2 import registry_manifest


def training():
    _, _, model = fixture(2)
    spec = deepcopy(model)
    spec.pop('prior')
    spec.pop('schema_version')
    for action in spec['actions']:
        for outcome in action['outcomes']:
            outcome.pop('likelihood')
    rows = [{'patient_id': 'train-' + d, 'visit_id': 'v1', 'split': 'train',
             'diagnosis': d, 'action_id': a['id'], 'outcome_id': '0'}
            for d in spec['diagnoses'] for a in spec['actions']]
    return spec, rows, model


def routing_rows():
    return [{'patient_id': 'train-' + str(i), 'decision_id': str(i), 'split': 'train',
             'agent_id': a['agent_id'], 'observation': {'chief_complaint': 'headache'},
             'correct': a['department'] == 'neurology'}
            for i in range(2) for a in registry_manifest()['agents'] if a['role'] == 'specialty']


class ResearchModelBuildingTests(unittest.TestCase):
    def test_counted_likelihoods_and_cost_free_v2(self):
        spec, rows, _ = training()
        fitted = fit_outcome_spec(spec, rows)
        self.assertEqual(fitted['schema_version'], 2)
        self.assertNotIn('cost_weights', fitted)
        self.assertTrue(all('cost' not in a for a in fitted['actions']))
        self.assertEqual(fitted['prior'], {d: .25 for d in spec['diagnoses']})
        # One observed result plus Dirichlet alpha=1 for four outcomes: 2/5.
        self.assertAlmostEqual(fitted['actions'][0]['outcomes'][0]['likelihood']['D0'], .4)
        self.assertEqual(fitted['provenance']['training_visits'], 4)
        InformationOutcomes(fitted)

    def test_no_smoothing_only_cells(self):
        spec, rows, _ = training()
        with self.assertRaisesRegex(ValueError, 'Insufficient observed'):
            fit_outcome_spec(spec, rows[1:])
        with self.assertRaisesRegex(ValueError, 'Insufficient observed'):
            fit_outcome_spec(spec, rows, min_observations=2)

    def test_patient_leakage_and_duplicate_rows(self):
        spec, rows, _ = training()
        with self.assertRaisesRegex(ValueError, 'overlap'):
            fit_outcome_spec(spec, rows, evaluation_patients=['train-D0'])
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            fit_outcome_spec(spec, rows + rows[:1])

    def test_both_models_compatible_and_no_input_mutation(self):
        spec, rows, _ = training()
        original = deepcopy(spec)
        result = build_models(evaluation_cases=[{'longitudinal': {'patient_id': 'held-out'}}],
            registry=registry_manifest(), routing_rows=routing_rows(), voi_spec=spec, voi_rows=rows)
        self.assertEqual(set(result), {'routing_utility', 'voi_model'})
        self.assertEqual(spec, original)
        self.assertEqual(result['routing_utility']['method'], 'jaccard_beta_accuracy_v2')

    def test_routing_failures_and_leakage_rejected(self):
        cases = [{'longitudinal': {'patient_id': 'held-out'}}]
        rows = routing_rows()
        rows[0]['audit'] = [{'status': 'failed'}]
        with self.assertRaisesRegex(ValueError, 'failed calls'):
            build_models(evaluation_cases=cases, registry=registry_manifest(), routing_rows=rows)
        with self.assertRaisesRegex(ValueError, 'overlap'):
            build_models(evaluation_cases=[{'longitudinal': {'patient_id': 'train-0'}}],
                         registry=registry_manifest(), routing_rows=routing_rows())

    def test_training_only_and_explicit_utility(self):
        spec, rows, _ = training()
        rows[0]['split'] = 'test'
        with self.assertRaisesRegex(ValueError, 'train-split'):
            fit_outcome_spec(spec, rows)
        spec['terminal_utility'] = None
        with self.assertRaisesRegex(ValueError, 'Explicit terminal utility'):
            fit_outcome_spec(spec, rows)

    def test_existing_fit_keeps_v1_and_v2(self):
        _, rows, model = training()
        self.assertEqual(fit_outcomes(model, rows)['schema_version'], 2)
        old = InformationOutcomes(model).artifact
        fitted = fit_outcomes(old, rows)
        self.assertEqual(fitted['schema_version'], 1)
        self.assertIn('cost_weights', fitted)


if __name__ == '__main__':
    unittest.main()
