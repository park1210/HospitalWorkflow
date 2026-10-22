import unittest
from app.core.agent_registry import AgentRegistry
from app.core.routing_utility import fit_utility
from app.scripts.prepare_hypothetical_pilot import build
from test_research_model_building import routing_rows
from test_research_math_v2 import registry_manifest
from test_encounter_pipeline import inputs, ScriptedSpecialist
from app.core.longitudinal_runner import run_longitudinal
from pathlib import Path
import json


class TieAndHypotheticalTests(unittest.TestCase):
    def test_all_fail_and_all_success_ties_abstain(self):
        manifest = registry_manifest()
        for correct in (False, True):
            rows = routing_rows()
            for r in rows:
                r['correct'] = correct
            model = fit_utility(rows, AgentRegistry(manifest))
            registry = AgentRegistry(manifest, model)
            result = registry.route({'chief_complaint': 'headache'}, ['neurology', 'cardiology'], mode='adaptive')
            self.assertEqual(result['decision_status'], 'abstained')
            self.assertIsNone(result['selected_specialty'])
            self.assertEqual(set(result['tied_departments']), {'neurology', 'cardiology'})

    def test_distinct_score_still_selects(self):
        manifest = registry_manifest()
        registry = AgentRegistry(manifest, fit_utility(routing_rows(), AgentRegistry(manifest)))
        self.assertEqual(registry.route({'chief_complaint': 'headache'}, ['neurology', 'cardiology'],
                                       mode='adaptive')['selected_specialty'], 'neurology')

    def test_hypothetical_runner_uses_declared_outcomes(self):
        manifest = json.loads(Path('app/data/synthea_v2/registry_shared_qwen.json').read_text(encoding='utf-8'))
        fixture = build(manifest)
        self.assertEqual(fixture, build(manifest))
        self.assertEqual(len(fixture['cases']), 15)
        report = run_longitudinal(fixture['cases'][:2], client=ScriptedSpecialist(),
            registry_manifest=fixture['registry'], routing_utility=fixture['routing_utility'],
            primary_router='adaptive', voi_model=fixture['voi_model'], minute_limit=120,
            diagnosis_catalog=list(fixture['voi_model']['diagnoses']),
            diagnosis_departments=fixture['voi_model']['diagnoses'])
        self.assertEqual(report['status'], 'completed')
        for visit in report['visits']:
            rt = next(iter(visit['final_state']['cases'].values()))
            self.assertNotIn('diagnosis_unresolved', rt['alerts'])
            self.assertEqual(rt['voi_state']['history'][0]['selected_action'], 'request_test')


if __name__ == '__main__':
    unittest.main()
