import copy
import unittest

from test_hospital_flow import cases
from app.core.hospital_experiments import run_experiments, validate_plan, render_summary
from app.core.hospital_parallel_scheduler import HospitalParallelScheduler
from app.core.hospital_flow import flow_report
from app.core.hospital_scheduler_state import HospitalSchedulerState


def plan():
    return {"schema_version": 1, "case_counts": [1, 3], "seeds": [7], "minute_limit": 150,
        "arrival_conditions": [{"name": "normal", "arrival": {"mode": "poisson", "rate_per_minute": 0.3}}],
        "resource_conditions": [{"name": "limited", "flow_config": {}},
            {"name": "reference", "flow_config": {"simulation": {"resource_mode": "cohort_unconstrained"}}}]}


class ExperimentTests(unittest.TestCase):
    def test_reproducible_and_input_immutable(self):
        inputs, settings = cases(3), plan()
        before = copy.deepcopy((inputs, settings))
        first = run_experiments(inputs, settings)
        second = run_experiments(inputs, settings)
        self.assertEqual(first, second)
        self.assertEqual((inputs, settings), before)
        self.assertEqual(len(first["runs"]), 4)
        self.assertEqual(len(first["paired_resource_comparisons"]), 2)
        for left, right in zip(first["runs"][::2], first["runs"][1::2]):
            self.assertEqual(left["source_cases"], right["source_cases"])
            self.assertEqual(left["experiment"]["realized_case_digest"], right["experiment"]["realized_case_digest"])
            self.assertNotEqual(left["experiment"]["condition_digest"], right["experiment"]["condition_digest"])

    def test_short_dataset_skips_without_cloning_patients(self):
        result = run_experiments(cases(1), plan())
        self.assertEqual(len(result["runs"]), 2)
        self.assertEqual(result["skipped"], [{"seed": 7, "case_count": 3, "reason": "insufficient_unique_cases"}])
        self.assertEqual(result["readiness"]["unavailable_case_counts"], [3])

    def test_unknown_or_confounding_plan_rejected(self):
        for extra in ({"durations": {"triage": 9}}, {"priority": {"risk": 9}}, {"arrival": {"seed": 2}}):
            settings = plan()
            settings["resource_conditions"][0]["flow_config"] = extra
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                validate_plan(settings)
        settings = plan()
        settings["arrival_conditions"][0]["name"] = "../outside"
        with self.assertRaises(ValueError):
            validate_plan(settings)

    def test_headless_reference_more_than_four_beds_and_specialists(self):
        inputs = cases(8)
        for case in inputs:
            case["gold_label"]["department"] = "cardiology"
        scheduler = HospitalParallelScheduler({"simulation": {"resource_mode": "cohort_unconstrained"}})
        state = scheduler.initialize(inputs)
        self.assertEqual(len(state.resources.er_beds), 8)
        self.assertEqual(len([r for r in state.resources.specialists
                              if state.resources.specialist_department(r) == "cardiology"]), 8)
        scheduler.run_until(state, 12)
        restored = HospitalSchedulerState.from_snapshot(state.snapshot(), {c["case_id"]: c for c in inputs})
        scheduler.run_until(state, 150)
        HospitalParallelScheduler().run_until(restored, 150)
        self.assertEqual(state.snapshot(), restored.snapshot())
        self.assertFalse(state.active_case_ids())
        report = flow_report(state)
        for name in ("triage_queue", "bed_queue", "test_queue", "specialty_queue"):
            self.assertEqual(report["queues"][name]["mean_completed_wait_min"], 0)
        self.assertEqual(report["conservation"]["system_time_residual"], 0)

    def test_missing_labels_and_incomplete_runs_not_zero_filled(self):
        settings = plan()
        settings["minute_limit"] = 1
        result = run_experiments(cases(3), settings)
        for row in result["condition_summaries"]:
            self.assertEqual(row["completed_runs"], 0)
            self.assertEqual(row["metrics"]["ttd"]["available_runs"], 0)
            self.assertIsNone(row["metrics"]["ttd"]["run_value_distribution"]["mean"])
        self.assertEqual(result["readiness"]["missing_annotations"]["required_tests"], ["P0", "P1", "P2"])
        self.assertIn("N/A", render_summary(result))
        self.assertFalse(result["readiness"]["research_claims"]["independent_clinical_accuracy"])

    def test_snapshot_retention_optional(self):
        result = run_experiments(cases(3), plan())
        self.assertTrue(all(not r["snapshots"] for r in result["runs"]))
        self.assertTrue(all(r["final_state"]["event_log"] for r in result["runs"]))

    def test_logical_resources_not_rendered_as_physical_beds(self):
        from app.core.live_parallel_visual_runtime import LiveParallelVisualRuntimeWriter
        state = HospitalParallelScheduler({"simulation": {"resource_mode": "cohort_unconstrained"}}).initialize(cases(5))
        writer = object.__new__(LiveParallelVisualRuntimeWriter)
        with self.assertRaises(ValueError):
            writer._write_snapshot(state, phase="initialized", actor="system", action="initialized")


if __name__ == "__main__":
    unittest.main()
