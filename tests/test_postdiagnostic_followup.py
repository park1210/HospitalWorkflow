import unittest

from app.core.hospital_case_runtime import HospitalCaseRuntime
from app.core.postdiagnostic_followup import followup_report, followup_from_summary


class PostdiagnosticTests(unittest.TestCase):
    def runtime(self):
        data = {"case_id": "followup", "temporal_profile": {"interventions": {
            "synthetic": {"delay_minutes": 4, "effect": {"spo2_delta": 2, "health_state": "Stable"}}},
            "natural_history_events": [{"minute": 6, "changes": {"health_state": "Critical"}}]}}
        return HospitalCaseRuntime("followup", data, arrival_time_min=10, arrival_index=0,
            current_time_min=12, final_diagnosis_min=12, is_completed=True,
            health_state="Worsening", vital_signs={"spo2": 94},
            interventions=[{"id": "synthetic", "time_min": 11, "effective_min": 15}])

    def test_delayed_treatment_then_worsening_and_source_unchanged(self):
        runtime = self.runtime()
        before = runtime.to_summary()
        report = followup_report([runtime], 5)
        rows = report["cases"][0]["trajectory"]
        self.assertEqual([r["minute"] for r in rows], [12, 15, 16, 17])
        self.assertEqual(rows[1]["vital_signs"]["spo2"], 96)
        self.assertEqual(rows[1]["health_state"], "Stable")
        self.assertEqual(rows[2]["health_state"], "Critical")
        self.assertEqual(runtime.to_summary(), before)
        self.assertEqual(report["llm_calls"], 0)
        self.assertEqual(sum(e["event_type"] == "intervention_response" for e in report["cases"][0]["events"]), 1)
        self.assertTrue(any(e["event_type"] == "review_needed" for e in report["cases"][0]["events"]))

    def test_saved_summary_reproduces_observation(self):
        runtime = self.runtime()
        summary = {"source_cases": [runtime.case_data], "final_state": {"cases": {runtime.case_id: runtime.to_summary()}}}
        self.assertEqual(followup_from_summary(summary, 5), followup_report([runtime], 5))

    def test_unfinished_skipped_and_missing_dynamics_not_recovery(self):
        runtime = self.runtime()
        runtime.case_data = {"case_id": runtime.case_id}
        runtime.interventions = []
        row = followup_report([runtime], 2)["cases"][0]
        self.assertTrue(row["data_gaps"])
        self.assertEqual(row["disposition_status"], "not_assessed")
        runtime.is_completed = False
        self.assertEqual(len(followup_report([runtime], 2)["skipped_cases"]), 1)

    def test_queue_wait_does_not_accumulate_after_exit(self):
        runtime = self.runtime()
        runtime.case_data["temporal_profile"] = {"flow_deterioration": {
            "clock": "queue_wait", "worsening_after_min": 1, "critical_after_min": 2}}
        runtime.interventions = []
        row = followup_report([runtime], 5)["cases"][0]
        self.assertEqual(row["trajectory"][-1]["health_state"], "Worsening")
        self.assertTrue(row["data_gaps"])

    def test_invalid_horizon_and_stale_completion_rejected(self):
        for value in (0, -1, True, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                followup_report([self.runtime()], value)
        runtime = self.runtime()
        runtime.current_time_min += 1
        with self.assertRaises(ValueError):
            followup_report([runtime], 5)

    def test_pending_effect_outside_horizon_and_missing_spec(self):
        runtime = self.runtime()
        row = followup_report([runtime], 1)["cases"][0]
        self.assertEqual(len(row["pending_interventions"]), 1)
        self.assertTrue(row["data_gaps"])
        runtime.case_data["temporal_profile"]["interventions"] = {}
        with self.assertRaises(ValueError):
            followup_report([runtime], 1)
