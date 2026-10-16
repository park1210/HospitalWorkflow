import itertools
import random
import unittest

from test_hospital_flow import cases
from app.core.hospital_flow import flow_config, flow_report, demand_report, validate_state
from app.core.hospital_flow_audit import validate_conservation
from app.core.hospital_parallel_scheduler import HospitalParallelScheduler


class MathematicalAuditTests(unittest.TestCase):
    def test_exogenous_load_and_capacity_bound(self):
        config = flow_config({"demand": {"er_doctors": {
            "arrival_rate_per_minute": 0.5, "mean_service_min": 4}}})
        row = demand_report(config)["resources"]["er_doctors"]
        self.assertEqual(row["offered_load"], 2)
        self.assertEqual(row["minimum_integer_capacity_for_load_below_one"], 3)
        self.assertEqual(row["load_condition"], "at_or_above_one")
        config["capacities"]["er_doctors"] = 0
        row = demand_report(config)["resources"]["er_doctors"]
        self.assertIsNone(row["offered_load"])
        self.assertEqual(row["load_condition"], "no_capacity")

    def test_mm1_reference_gated_and_known_values(self):
        config = flow_config({"demand": {"er_doctors": {
            "arrival_rate_per_minute": 0.2, "mean_service_min": 2,
            "model": "mm1_fixed_priority", "priority_arrival_rates": [0.1, 0.1]}}})
        waits = demand_report(config)["resources"]["er_doctors"]["reference_wait_by_priority_min"]
        self.assertAlmostEqual(waits[0], 1)
        self.assertAlmostEqual(waits[1], 5 / 3)
        config["capacities"]["er_doctors"] = 2
        self.assertIsNone(demand_report(config)["resources"]["er_doctors"]["reference_wait_by_priority_min"])
        config["capacities"]["er_doctors"] = 1
        config["demand"]["er_doctors"].update(arrival_rate_per_minute=0.5, priority_arrival_rates=[0.2, 0.3])
        self.assertIsNone(demand_report(config)["resources"]["er_doctors"]["reference_wait_by_priority_min"])

    def test_invalid_demand_rejected(self):
        for demand in ({"arrival_rate_per_minute": -1, "mean_service_min": 1},
                       {"arrival_rate_per_minute": 1, "mean_service_min": 0},
                       {"arrival_rate_per_minute": 1, "mean_service_min": 1,
                        "model": "mm1_fixed_priority", "priority_arrival_rates": [0.2]}):
            with self.subTest(demand=demand), self.assertRaises(ValueError):
                flow_config({"demand": {"er_doctors": demand}})

    def test_stall_explained_and_future_arrival_not_stall(self):
        scheduler = HospitalParallelScheduler({"capacities": {"er_doctors": 0}})
        state = scheduler.initialize(cases(1))
        self.assertFalse(flow_report(state)["progress"]["currently_stalled"])
        scheduler.run_until(state, 10)
        report = flow_report(state)
        self.assertTrue(report["progress"]["currently_stalled"])
        self.assertEqual(report["progress"]["waiting"][0]["required_resource"], "er_doctor")
        self.assertEqual(report["progress"]["waiting"][0]["reason"], "no_configured_resource")

    def test_corrupted_integral_rejected(self):
        scheduler = HospitalParallelScheduler()
        state = scheduler.initialize(cases(1))
        scheduler.step(state)
        state.flow_accounting["system"]["area"] += 1
        with self.assertRaises(ValueError):
            validate_conservation(state)

    def test_lost_patient_and_capacity_mutation_rejected(self):
        state = HospitalParallelScheduler().initialize(cases(1))
        state.arrival_queue.clear()
        with self.assertRaises(ValueError):
            validate_state(state)
        state.arrival_queue.append("P0")
        state.resources.er_doctors.clear()
        with self.assertRaises(ValueError):
            validate_state(state)

    def test_completed_and_censored_system_time(self):
        scheduler = HospitalParallelScheduler()
        state = scheduler.initialize(cases(3))
        for _ in range(80):
            scheduler.step(state)
            report = flow_report(state)["conservation"]
            self.assertEqual(report["system_time_residual"], 0)
            self.assertEqual(report["cohort_size"], report["not_arrived"] + report["in_system"] + report["completed"])
        self.assertFalse(state.active_case_ids())
        self.assertEqual(report["system_area_patient_minutes"], sum(
            c.final_diagnosis_min - c.arrival_time_min for c in state.cases.values()))

    def test_bounded_configuration_sweep(self):
        # 72 finite workloads. This is bounded testing, never a universal proof.
        for seed, doctors, nurses, labs in itertools.product(range(3), (0, 1, 3), (1, 2), (0, 1, 2, 3)):
            with self.subTest(seed=seed, doctors=doctors, nurses=nurses, labs=labs):
                rng = random.Random(seed)
                inputs = cases(5)
                for case in inputs:
                    case["temporal_profile"]["arrival_time_min"] = rng.randrange(15)
                    case["resource_profile"]["test_turnaround"]["Blood Test"] = rng.randrange(1, 10)
                scheduler = HospitalParallelScheduler({"capacities": {
                    "er_doctors": doctors, "triage_nurses": nurses, "lab_slots": labs},
                    "durations": {"er_assessment": 1 + seed}})
                state = scheduler.initialize(inputs)
                scheduler.run_until(state, 180)
                report = flow_report(state)
                self.assertEqual(report["conservation"]["system_time_residual"], 0)
                self.assertTrue(all(v == 0 for v in report["conservation"]["queue_time_residuals"].values()))
                self.assertTrue(all(0 <= g["utilization"] <= 1 for g in report["resource_groups"].values()))
                if doctors and labs:
                    self.assertFalse(state.active_case_ids())
                else:
                    self.assertEqual(report["termination"], "incomplete")
                    self.assertTrue(report["progress"]["currently_stalled"])


if __name__ == "__main__":
    unittest.main()
