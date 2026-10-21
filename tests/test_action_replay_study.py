from copy import deepcopy
import json
import unittest

from app.scripts.prepare_action_replay_study import prepare
from app.core.information_outcomes import InformationOutcomes
from app.core.clinical_observation import prepare_encounter
from app.core.memory_evaluation import visit_key
from app.core.longitudinal_runner import run_longitudinal
from app.core.paper_evaluation import episode_rows
from test_research_math_v2 import registry_manifest
from test_encounter_pipeline import ScriptedSpecialist


def inputs():
    cases, labels, departments = [], {}, {}
    for i in range(8):
        patient, diagnosis = 'p' + str(i), 'A' if i < 4 else 'B'
        case = {'case_id': patient, 'longitudinal': {'patient_id': patient},
                'index_encounter_id': 'v1', 'index_encounter_start': '2026-01-01T00:00:00Z',
                'past_visits': [], 'current_initial_state': {
                    'doctor_visible_info': {'chief_complaint': 'headache'},
                    'patient_visible_info': {'associated_symptoms': ['headache']}},
                'current_encounter_events': [{'event_id': patient + '-test', 'action': 'Test',
                    'target': 'Patient-specific test ' + patient, 'available_minute': 0,
                    'evidence': json.dumps({'records': [{'code': 'X', 'event_type': 'observations',
                        'recorded_evidence': {'units': 'unit', 'value': str(i)}}]})}]}
        cases.append(case)
        key = visit_key({'patient_id': patient, 'visit_id': 'v1'})
        labels[key] = [diagnosis]
        departments[key] = ['neurology' if diagnosis == 'A' else 'cardiology']
    return cases, labels, departments, registry_manifest()


class ReplayStudyTests(unittest.TestCase):
    def test_split_common_actions_and_train_only_thresholds(self):
        source = inputs()
        original = deepcopy(source)
        prepared = prepare(*source)
        report = prepared['study_report']
        self.assertFalse(set(report['train_patients']) & set(report['test_patients']))
        self.assertEqual(len(prepared['voi_model']['actions']), 1)
        for c in prepared['cases']:
            prepare_encounter(c)
            self.assertIn('visit_id', c['longitudinal'])
        for c in source[0]:
            if c['longitudinal']['patient_id'] in report['test_patients']:
                payload = json.loads(c['current_encounter_events'][0]['evidence'])
                payload['records'][0]['recorded_evidence']['value'] = '9999'
                c['current_encounter_events'][0]['evidence'] = json.dumps(payload)
        changed = prepare(*source)
        self.assertEqual(prepared['voi_model'], changed['voi_model'])
        self.assertEqual(original[0][0]['current_encounter_events'][0]['target'], 'Patient-specific test p0')

    def test_released_bin_updates_belief_and_retains_raw_evidence(self):
        prepared = prepare(*inputs())
        model = InformationOutcomes(prepared['voi_model'])
        event = prepared['cases'][0]['current_encounter_events'][0]
        self.assertIn('source_evidence', json.loads(event['evidence']))
        before, matches = model.observe({})
        self.assertFalse(matches)
        after, matches = model.observe({'objective_findings': [event['target'] + ': ' + event['evidence']]})
        self.assertNotEqual(before, after)
        self.assertEqual(len(matches), 1)
        with self.assertRaisesRegex(ValueError, 'Unknown released'):
            model.observe({'objective_findings': [event['target'] + ': ' + json.dumps({'replay_bin': 'invented'})]})

    def test_runner_b4_and_no_double_counting(self):
        prepared = prepare(*inputs())
        cases = prepared['cases'][:1]
        report = run_longitudinal(cases, client=ScriptedSpecialist(), registry_manifest=prepared['registry'],
            primary_router='adaptive', voi_model=prepared['voi_model'], minute_limit=120)
        self.assertEqual(report['status'], 'completed')
        rt = next(iter(report['visits'][0]['final_state']['cases'].values()))
        self.assertEqual(rt['voi_state']['history'][0]['selected_action'], 'request_test')
        # No fabricated clinical support: statistical prediction is not a supported diagnosis.
        self.assertEqual(rt['voi_state']['history'][-1]['target'], 'Unresolved')
        metrics = episode_rows(cases, prepared['labels'], report, 'B4', 1)
        self.assertEqual(metrics[0]['actions'], sum(bool(c.get('decision')) for c in rt['llm_audit']))


if __name__ == '__main__':
    unittest.main()
