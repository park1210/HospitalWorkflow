import unittest

from test_hospital_flow import cases
from app.core.hospital_test_model import test_resource_type, test_timing

# These are production helper functions, not pytest test cases.
test_resource_type.__test__ = False
test_timing.__test__ = False
from app.core.hospital_flow import flow_report, validate_state
from app.core.hospital_parallel_scheduler import HospitalParallelScheduler
from app.core.hospital_scheduler_state import HospitalSchedulerState


class TestResourceTiming(unittest.TestCase):
    def setup_run(self):
        inputs = cases(2)
        for case, occupancy, turnaround in zip(inputs, (2, 20), (10, 25)):
            case["resource_profile"].update(
                test_occupancy={"Blood Test": occupancy},
                test_turnaround={"Blood Test": turnaround},
                test_resources={"Blood Test": "lab_slot"})
        scheduler = HospitalParallelScheduler({"capacities": {
            "er_doctors": 2, "triage_nurses": 2, "lab_slots": 1}})
        return scheduler, scheduler.initialize(inputs), inputs

    def test_routing_shared_and_token_boundaries(self):
        self.assertEqual(test_resource_type("Lactate"), "lab_slot")
        self.assertEqual(test_resource_type("Ultrasound"), "imaging_slot")
        self.assertEqual(test_resource_type("Chest CT"), "imaging_slot")
        self.assertEqual(test_resource_type("Custom", {"resource_profile": {
            "test_resources": {"Custom": "imaging_slot"}}}), "imaging_slot")

    def test_bad_timing_rejected_before_run(self):
        for value in (-1, float("nan"), 8):
            inputs = cases(1)
            inputs[0]["resource_profile"]["test_occupancy"] = {"Blood Test": value}
            with self.subTest(value=value), self.assertRaises(ValueError):
                HospitalParallelScheduler().initialize(inputs)

    def test_reuse_before_result_does_not_release_new_owner(self):
        scheduler, state, _ = self.setup_run()
        for _ in range(100):
            scheduler.step(state)
            if "Blood Test" in state.case("P0").completed_tests:
                break
        self.assertEqual(state.resources.lab_slots[0].assigned_case_id, "P1")
        starts = [e for e in state.event_log if e["event_type"] == "test_started"]
        self.assertEqual(starts[1]["minute"] - starts[0]["minute"], 2)
        self.assertTrue(state.case("P1").pending_results)
        scheduler.run_until(state, 180)
        self.assertFalse(state.active_case_ids())
        report = flow_report(state)
        self.assertEqual(report["resource_groups"]["lab_slot"]["busy_minutes"], 22)
        self.assertEqual(report["conservation"]["system_time_residual"], 0)
        self.assertFalse(any(g["code"] == "missing_test_occupancy" for g in report["data_gaps"]))

    def test_resume_while_result_pending_after_release(self):
        scheduler, state, inputs = self.setup_run()
        for _ in range(100):
            scheduler.step(state)
            if state.resources.lab_slots[0].assigned_case_id == "P1":
                break
        restored = HospitalSchedulerState.from_snapshot(state.snapshot(), {c["case_id"]: c for c in inputs})
        scheduler.run_until(state, 180)
        HospitalParallelScheduler().run_until(restored, 180)
        self.assertEqual(state.snapshot(), restored.snapshot())

    def test_await_preserves_release_and_diagnose_cancels_both(self):
        scheduler, state, _ = self.setup_run()
        for _ in range(100):
            scheduler.step(state)
            if state.case("P0").pending_results:
                break
        scheduler.apply_branch_action(state, case_id="P0", selected_action={"type": "await_results"})
        events = {e["event_type"] for e in state.scheduled_events if e["case_id"] == "P0"}
        self.assertEqual(events, {"test_resource_release", "test_result_ready"})
        scheduler.apply_branch_action(state, case_id="P0", selected_action={"type": "diagnose"})
        validate_state(state)
        self.assertFalse(any(e["case_id"] == "P0" for e in state.scheduled_events))
        scheduler.run_until(state, 180)
        self.assertFalse(state.active_case_ids())

    def test_fallback_reported_and_audit_uses_explicit_route(self):
        inputs = cases(1)
        inputs[0]["resource_profile"]["test_resources"] = {"Blood Test": "imaging_slot"}
        scheduler = HospitalParallelScheduler({"capacities": {"imaging_slots": 0}})
        state = scheduler.initialize(inputs)
        scheduler.run_until(state, 30)
        report = flow_report(state)
        self.assertEqual(report["progress"]["waiting"][0]["required_resource"], "imaging_slot")
        self.assertTrue(report["progress"]["currently_stalled"])
        scheduler = HospitalParallelScheduler()
        state = scheduler.initialize(cases(1))
        scheduler.run_until(state, 100)
        self.assertTrue(any(g["code"] == "missing_test_occupancy" for g in flow_report(state)["data_gaps"]))


if __name__ == "__main__":
    unittest.main()
