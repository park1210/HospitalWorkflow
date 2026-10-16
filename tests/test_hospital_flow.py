"""Flow regression tests use artificial cases, no API calls or clinical cutoffs."""
import copy
import unittest

from app.core.hospital_flow import (flow_config, flow_report, schedule_arrivals,
    validate_state, sync_queues, offered_load, mm1_priority_reference)
from app.core.hospital_parallel_scheduler import HospitalParallelScheduler
from app.core.hospital_scheduler_state import HospitalSchedulerState


def cases(count=3):
    return [{"case_id": "P%d" % i,
             "doctor_visible_info": {"chief_complaint": "synthetic complaint"},
             "temporal_profile": {"arrival_time_min": 0},
             "meta": {"demo": {"decisive_tests": ["Blood Test"]}},
             "hidden_test_results": {"Blood Test": {"result": "synthetic result"}},
             "resource_profile": {"test_turnaround": {"Blood Test": 7}},
             "gold_label": {"diagnosis": "synthetic", "department": "general_medicine"}}
            for i in range(count)]


class FlowTests(unittest.TestCase):
    def run_cases(self, config=None, inputs=None, horizon=180):
        scheduler = HospitalParallelScheduler(config)
        state = scheduler.initialize(cases() if inputs is None else inputs)
        scheduler.run_until(state, horizon)
        return scheduler, state

    def test_invalid_config(self):
        for config in ({"capacities": {"er_doctors": -1}},
                       {"capacities": {"er_beds": 5}},
                       {"durations": {"triage": float("nan")}},
                       {"priority": {"waiting": -1}}, {"unknown": {}}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                flow_config(config)

    def test_seeded_arrivals_and_input_isolation(self):
        inputs = cases(12)
        before = copy.deepcopy(inputs)
        config = flow_config({"arrival": {"mode": "poisson", "seed": 42}})
        first = schedule_arrivals(inputs, config)
        self.assertEqual(first, schedule_arrivals(inputs, config))
        self.assertEqual(inputs, before)
        times = [c["temporal_profile"]["arrival_time_min"] for c in first]
        self.assertEqual(times, sorted(times))
        with self.assertRaises(ValueError):
            schedule_arrivals([inputs[0], inputs[0]], config)

    def test_resource_cannot_be_allocated_twice(self):
        state = HospitalParallelScheduler().initialize(cases())
        resource = state.resources.er_doctors[0]
        resource.acquire("P0", 0, 3)
        with self.assertRaises(ValueError):
            resource.acquire("P1", 0, 3)

    def test_duplicate_queue_rejected(self):
        state = HospitalParallelScheduler().initialize(cases())
        state.er_queue.append("P0")
        with self.assertRaises(ValueError):
            validate_state(state)

    def test_completion_conservation_and_utilization(self):
        _, state = self.run_cases()
        report = flow_report(state)
        self.assertEqual(report["termination"], "completed")
        for q in report["queues"].values():
            self.assertEqual(q["little_law_area_residual_patient_minutes"], 0)
        for group in report["resource_groups"].values():
            self.assertGreaterEqual(group["utilization"], 0)
            self.assertLessEqual(group["utilization"], 1)
        self.assertIsNone(report["wte"])
        for runtime in state.cases.values():
            self.assertLess(runtime.first_evaluation_min, runtime.final_diagnosis_min)
            self.assertGreater(runtime.er_turn_count, 1)
            self.assertLess(runtime.queue_wait_minutes, runtime.final_diagnosis_min)

    def test_multiple_doctors_and_service_not_queue_wait(self):
        scheduler = HospitalParallelScheduler({"capacities": {"triage_nurses": 3, "er_doctors": 3},
                                               "durations": {"er_assessment": 4}})
        state = scheduler.initialize(cases())
        scheduler.run_until(state, 3)
        self.assertEqual(sum(r.status != "idle" for r in state.resources.er_doctors), 3)
        scheduler.step(state)
        first = {cid: c.first_evaluation_min for cid, c in state.cases.items()}
        waits = {cid: c.queue_wait_minutes for cid, c in state.cases.items()}
        for _ in range(3):
            scheduler.step(state)
        self.assertEqual(waits, {cid: c.queue_wait_minutes for cid, c in state.cases.items()})
        scheduler.run_until(state, 180)
        self.assertEqual(first, {cid: c.first_evaluation_min for cid, c in state.cases.items()})
        self.assertFalse(state.active_case_ids())

    def test_case_turnaround_used(self):
        scheduler = HospitalParallelScheduler()
        state = scheduler.initialize(cases(1))
        for _ in range(30):
            scheduler.step(state)
            pending = [e for e in state.scheduled_events if e["event_type"] == "test_result_ready"]
            if pending:
                self.assertEqual(pending[0]["execute_minute"] - (state.current_minute - 1), 7)
                return
        self.fail("No test started")

    def test_zero_capacity_censored_conservation(self):
        _, state = self.run_cases({"capacities": {"er_doctors": 0}}, horizon=20)
        report = flow_report(state)
        self.assertEqual(report["termination"], "incomplete")
        self.assertEqual(report["not_evaluated_count"], 3)
        self.assertIsNone(report["wte"])
        self.assertGreater(report["queues"]["er_queue"]["open_visits"], 0)
        self.assertTrue(all(q["little_law_area_residual_patient_minutes"] == 0
                            for q in report["queues"].values()))

    def test_explicit_deterioration_relative_to_arrival(self):
        inputs = cases(2)
        inputs[0]["temporal_profile"] = {"arrival_time_min": 5, "flow_deterioration": {
            "clock": "since_arrival", "worsening_after_min": 2, "critical_after_min": 4}}
        scheduler = HospitalParallelScheduler({"capacities": {"er_doctors": 0}})
        state = scheduler.initialize(inputs)
        scheduler.run_until(state, 7)
        self.assertEqual(state.case("P0").health_state, "Stable")
        scheduler.step(state)
        self.assertEqual(state.case("P0").health_state, "Worsening")
        scheduler.run_until(state, 10)
        self.assertEqual(state.case("P0").health_state, "Critical")
        self.assertEqual(state.case("P1").health_state, "Stable")
        self.assertLess(scheduler._priority_key(state.case("P0")), scheduler._priority_key(state.case("P1")))

    def test_queue_clock_excludes_triage_service(self):
        inputs = cases(1)
        inputs[0]["temporal_profile"]["flow_deterioration"] = {
            "clock": "queue_wait", "worsening_after_min": 2, "critical_after_min": 4}
        scheduler = HospitalParallelScheduler({"durations": {"triage": 5}, "capacities": {"er_doctors": 0}})
        state = scheduler.initialize(inputs)
        scheduler.run_until(state, 6)
        self.assertEqual(state.case("P0").health_state, "Stable")
        scheduler.run_until(state, 10)
        self.assertEqual(state.case("P0").health_state, "Critical")

    def test_snapshot_resume_and_isolation(self):
        scheduler = HospitalParallelScheduler({"capacities": {"er_doctors": 2}})
        state = scheduler.initialize(cases())
        scheduler.run_until(state, 8)
        snapshot = state.snapshot()
        frozen = copy.deepcopy(snapshot)
        restored = HospitalSchedulerState.from_snapshot(snapshot, {c["case_id"]: c for c in cases()})
        scheduler.run_until(state, 180)
        HospitalParallelScheduler().run_until(restored, 180)
        self.assertEqual(state.snapshot(), restored.snapshot())
        self.assertEqual(snapshot, frozen)

    def test_branch_cancels_pending_work(self):
        scheduler = HospitalParallelScheduler()
        state = scheduler.initialize(cases(1))
        while not state.case("P0").pending_results:
            scheduler.step(state)
        before = state.snapshot()
        with self.assertRaises(ValueError):
            scheduler.apply_branch_action(state, case_id="P0", selected_action={"type": "ask_patient"})
        self.assertEqual(before, state.snapshot())
        scheduler.apply_branch_action(state, case_id="P0", selected_action={"type": "diagnose", "target": "branch"})
        sync_queues(state)
        validate_state(state)
        self.assertFalse(state.scheduled_events)
        self.assertFalse(any(r.assigned_case_id == "P0" for r in state.resources.all_resources()))

    def test_empty_await_and_branch_waits_to_horizon(self):
        scheduler = HospitalParallelScheduler()
        state = scheduler.initialize(cases(1))
        scheduler.run_until(state, 4)
        scheduler.apply_branch_action(state, case_id="P0", selected_action={"type": "await_results"})
        # Simulate no ER capacity after a branch: absence of an own event is not completion.
        state.resources.er_doctors.clear()
        state.flow_config["capacities"]["er_doctors"] = 0
        start = state.current_minute
        scheduler.run_branch_until_stable(state, case_id="P0", minute_horizon=5)
        self.assertEqual(state.current_minute, start + 5)
        self.assertFalse(state.case("P0").is_completed)

    def test_wte_independent_labels_and_zero_denominator(self):
        state = HospitalParallelScheduler().initialize(cases(2))
        for i, c in enumerate(state.cases.values()):
            c.case_data["evaluation"] = {"critical_patient": i == 0}
            c.first_evaluation_min = 2 + i * 4
        self.assertEqual(flow_report(state)["wte"], 0.5)
        for c in state.cases.values():
            c.first_evaluation_min = 0
        self.assertIsNone(flow_report(state)["wte"])

    def test_reference_math_and_unstable_rejection(self):
        self.assertAlmostEqual(offered_load(0.2, 3, 2), 0.3)
        self.assertAlmostEqual(mm1_priority_reference([0.2], 0.5)[0], 4 / 3)
        with self.assertRaises(ValueError):
            mm1_priority_reference([0.5], 0.5)


if __name__ == "__main__":
    unittest.main()
