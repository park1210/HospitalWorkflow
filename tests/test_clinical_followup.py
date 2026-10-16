import unittest

from test_diagnostic_gate import Client, response, source
from app.core.clinical_followup import available_consult_departments, review_signature
from app.core.hospital_parallel_scheduler import HospitalParallelScheduler
from app.core.hospital_case_runtime import HospitalCaseRuntime
from app.core.hospital_flow import validate_state, flow_report


class FollowupTests(unittest.TestCase):
    def test_same_department_requires_changed_observations(self):
        runtime = HospitalParallelScheduler().initialize([source()]).case("gate")
        runtime.consult_history = [{"department": "neurology", "review_signature": review_signature(runtime)}]
        runtime.current_time_min += 10
        runtime.consult_history[0]["opinion"] = "new wording"
        self.assertEqual(available_consult_departments(runtime, ["neurology"]), [])
        runtime.objective_findings.append("T: released finding")
        self.assertEqual(available_consult_departments(runtime, ["neurology"]), ["neurology"])
        runtime.consult_history.append({"department": "neurology", "review_signature": review_signature(runtime)})
        self.assertEqual(available_consult_departments(runtime, ["neurology"]), [])

    def test_specialist_can_review_result_of_own_order(self):
        client = Client(response("consult_specialty", target="neurology"),
                        response("request_test", target="T"),
                        response("consult_specialty", target="neurology"),
                        response(certainty="supported", indices=[0]))
        scheduler = HospitalParallelScheduler({"clinical": {"mode": "llm_required"}}, llm_client=client)
        state = scheduler.initialize([source()])
        scheduler.run_until(state, 100)
        runtime = state.case("gate")
        self.assertTrue(runtime.is_completed)
        self.assertEqual([c["department"] for c in runtime.consult_history], ["neurology", "neurology"])
        self.assertEqual(len(runtime.llm_audit), 4)
        self.assertEqual(runtime.disposition_status, "not_assessed")
        self.assertEqual(runtime.zone, "diagnostic_episode_complete")
        self.assertNotIn("discharge_1", runtime.movement_path)
        self.assertEqual(flow_report(state)["conservation"]["system_time_residual"], 0)

    def test_worsening_during_pending_test_triggers_one_review_and_preserves_result(self):
        data = source()
        data["resource_profile"] = {"test_occupancy": {"T": 2}, "test_turnaround": {"T": 20},
                                    "test_resources": {"T": "lab_slot"}}
        data["temporal_profile"] = {"interventions": {
            "synthetic_support": {"delay_minutes": 0, "effect": {"health_state": "Stable"}}}}
        client = Client(response("request_test", target="T"),
                        response("treat", target="synthetic_support"),
                        response(certainty="supported", indices=[0]))
        scheduler = HospitalParallelScheduler({"clinical": {"mode": "llm_required"}}, llm_client=client)
        state = scheduler.initialize([data])
        runtime = state.case("gate")
        while not runtime.pending_results:
            scheduler.step(state)
        ready = runtime.pending_results[0]["ready_minute"]
        runtime.case_data["temporal_profile"]["natural_history_events"] = [
            {"minute": state.current_minute, "changes": {"health_state": "Critical"}}]
        while len(client.payloads) < 2:
            scheduler.step(state)
        self.assertLess(state.current_minute, ready)
        self.assertTrue(runtime.pending_results)
        self.assertEqual(runtime.health_state, "Stable")  # zero-delay effect already applied
        self.assertNotIn("diagnose", client.payloads[1]["allowed_actions"])
        self.assertTrue(client.payloads[1]["observation"]["reassessment_pending"])
        self.assertTrue(any(e["event_type"] == "test_result_ready" for e in state.scheduled_events))
        restored = HospitalCaseRuntime.from_summary(runtime.to_summary(), runtime.case_data)
        self.assertEqual(restored.reassessment_reason, runtime.reassessment_reason)
        scheduler.run_until(state, 100)
        validate_state(state)
        self.assertTrue(runtime.is_completed)
        self.assertEqual(runtime.completed_tests, ["T"])
        self.assertEqual(len(client.payloads), 3)
        self.assertEqual(sum(e["action"] == "reassessment_requested" for e in state.event_log), 1)

    def test_result_during_active_review_preserves_route(self):
        data = source()
        data["resource_profile"] = {"test_occupancy": {"T": 1}, "test_turnaround": {"T": 3},
                                    "test_resources": {"T": "lab_slot"}}
        client = Client(response("request_test", target="T"), response(certainty="supported", indices=[0]))
        scheduler = HospitalParallelScheduler({"clinical": {"mode": "llm_required"}}, llm_client=client)
        state = scheduler.initialize([data])
        runtime = state.case("gate")
        while not runtime.pending_results:
            scheduler.step(state)
        runtime.workflow_state = "waiting_er"
        runtime.reassessment_pending = True
        state.er_queue.append(runtime.case_id)
        # Arrival of the released result must preserve the scheduled review.
        event = next(e for e in state.scheduled_events if e["event_type"] == "test_result_ready")
        scheduler._handle_test_result_event(state, event)
        self.assertEqual(runtime.workflow_state, "waiting_er")
        self.assertEqual(state.er_queue, [runtime.case_id])
        self.assertFalse(any(e["event_type"] == "return_from_results" for e in state.scheduled_events))


if __name__ == "__main__":
    unittest.main()
