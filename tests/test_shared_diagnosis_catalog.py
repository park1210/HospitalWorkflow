import unittest
from app.core.longitudinal_runner import run_longitudinal
from test_encounter_pipeline import inputs, ScriptedSpecialist


class SharedDiagnosisCatalogTests(unittest.TestCase):
    def test_shared_mapping_reaches_agent_and_report(self):
        cases, registry = inputs()
        client = ScriptedSpecialist()
        mapping = {'A': 'neurology', 'B': 'pulmonology'}
        result = run_longitudinal(cases[:1], client=client, registry_manifest=registry,
            diagnosis_catalog=list(mapping), diagnosis_departments=mapping, minute_limit=60)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['diagnosis_departments'], mapping)
        for _, payload in client.payloads:
            self.assertEqual(payload['diagnosis_catalog'], ['A', 'B'])
            self.assertEqual(payload['diagnosis_department_catalog'], mapping)
            self.assertEqual(payload['department_catalog'], ['neurology', 'pulmonology'])
            self.assertNotIn('expected_diagnoses', payload)

    def test_partial_or_noncanonical_mapping_rejected_before_calls(self):
        cases, registry = inputs()
        for mapping in ({'A': 'neurology'}, {'A': 'neurology', 'B': 'invented_department'}):
            with self.assertRaisesRegex(ValueError, 'catalog'):
                run_longitudinal(cases[:1], client=ScriptedSpecialist(), registry_manifest=registry,
                    diagnosis_catalog=['A', 'B'], diagnosis_departments=mapping)


if __name__ == '__main__':
    unittest.main()
