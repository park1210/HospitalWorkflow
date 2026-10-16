"""No external inference: exercise real scheduler transitions with scripted roles."""
import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

from app.agents.patient_agent import PatientAgent
from app.core.hospital_parallel_scheduler import HospitalParallelScheduler
from app.core.hospital_scheduler_state import HospitalSchedulerState
from app.core.hospital_flow import validate_state, flow_report
from app.llm.role_call import RoleCallError
from app.modules.deterioration_module import DeteriorationModule


def decision(action, target, **extra):
    return json.dumps(dict(action=action, target=target, rationale="Review the observed symptoms and evidence.",
                          assessment="unresolved complaint", department="general_medicine", **extra))


def case():
    return {"case_id": "llm-test", "patient_visible_info": {"history": "Pain started today.",
            "associated_symptoms": ["pain"]},
            "doctor_visible_info": {"chief_complaint": "pain", "initial_vitals": {"spo2": 98}},
            "gold_label": {"diagnosis": "SECRET_GOLD", "department": "neurology"},
            "hidden_test_results": {"Blood Test": {"result": "SECRET_RESULT"}},
            "available_tests": ["Blood Test"],
            "temporal_profile": {"arrival_time_min": 0, "natural_history_events": [
                {"minute": 1, "changes": {"spo2_delta": -2, "new_symptoms": ["breathlessness"]}}]}}


class ScriptedClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def chat(self, system, user, model=None):
        self.calls.append((model, json.loads(user)))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class LLMRoleTests(unittest.TestCase):
    def run_case(self, responses, source=None, **clinical):
        client = ScriptedClient(responses)
        scheduler = HospitalParallelScheduler({"clinical": {"mode": "llm_required", **clinical}}, llm_client=client)
        state = scheduler.initialize([source or case()])
        scheduler.run_until(state, 100)
        validate_state(state)
        return scheduler, state, client

    def test_all_roles_and_private_observations(self):
        _, state, client = self.run_case([
            decision("ask_patient", "What do you feel now?"), '{"fact_ids":["current:1"],"unknown":false}',
            decision("request_test", "Blood Test"),
            decision("consult_specialty", "neurology"),
            decision("diagnose", "observed syndrome", certainty="supported", evidence_indices=[0])])
        runtime = state.case("llm-test")
        self.assertTrue(runtime.is_completed)
        self.assertEqual([r["role"] for r in runtime.llm_audit], ["er", "patient", "er", "er", "specialty"])
        self.assertEqual(runtime.vital_signs["spo2"], 96)
        self.assertEqual(runtime.question_history[0]["question"], "What do you feel now?")
        self.assertTrue(any("breathlessness" in f["text"] for f in client.calls[1][1]["facts"]))
        prompts = [json.dumps(c[1]) for c in client.calls]
        self.assertTrue(all("SECRET_GOLD" not in p for p in prompts))
        self.assertTrue(all("SECRET_RESULT" not in p for p in prompts[:3]))
        self.assertIn("SECRET_RESULT", prompts[3])
        self.assertNotIn("vital_signs", client.calls[1][1])
        self.assertEqual(flow_report(state)["llm_calls"], 5)
        restored = HospitalSchedulerState.from_snapshot(state.snapshot(), {runtime.case_id: runtime.case_data})
        self.assertEqual(restored.case(runtime.case_id).to_summary(), runtime.to_summary())

    def test_specialty_can_interview_and_order_test(self):
        for followup in [decision("ask_patient", "Has anything changed?"), decision("request_test", "Blood Test")]:
            responses = [decision("consult_specialty", "neurology"), followup]
            if 'ask_patient' in followup:
                responses.append('{"fact_ids":["current:0"],"unknown":false}')
            responses.append(decision("diagnose", "unresolved pain", certainty="unresolved"))
            _, state, _ = self.run_case(responses, max_decisions=3)
            self.assertTrue(state.case("llm-test").is_completed)
            self.assertIn("diagnosis_unresolved", state.case("llm-test").alerts)
            self.assertEqual(len(state.case("llm-test").consult_history), 1)

    def test_failures_are_recorded_without_fallback(self):
        for response in [RuntimeError("offline"), "not json", decision("request_test", "invented test"),
                         decision("ask_patient", "pain"),
                         decision("diagnose", "invented certainty", certainty="supported", evidence_indices=[99])]:
            client = ScriptedClient([response])
            scheduler = HospitalParallelScheduler({"clinical": {"mode": "llm_required"}}, llm_client=client)
            state = scheduler.initialize([case()])
            with self.assertRaises(RoleCallError):
                scheduler.run_until(state, 100)
            row = state.case("llm-test").llm_audit[-1]
            self.assertEqual(row["status"], "error")
            self.assertFalse(row["fallback_used"])
            self.assertFalse(state.case("llm-test").is_completed)

    def test_decision_budget_does_not_fabricate_success(self):
        _, state, client = self.run_case([decision("diagnose", "unresolved", certainty="unresolved")], max_decisions=1)
        self.assertEqual(client.calls[0][1]["allowed_actions"], ["diagnose"])
        self.assertIn("diagnosis_unresolved", state.case("llm-test").alerts)

    def test_patient_history_calls_model_and_receives_dynamic_state(self):
        runtime = SimpleNamespace(current_symptoms=["breathlessness"], current_time_min=10,
                                  arrival_time_min=0, llm_audit=[], llm_call_count=0)
        with patch("app.agents.patient_agent.settings.USE_LLM_FOR_PATIENT_AGENT", True):
            patient = PatientAgent(case())
            patient.client = ScriptedClient(['{"fact_ids":["history:0"],"unknown":false}'])
            self.assertEqual(patient.answer("When did your symptoms start?", runtime), "Pain started today.")
            self.assertEqual(runtime.llm_call_count, 1)
            self.assertEqual(runtime.llm_audit[0]["status"], "success")
            self.assertNotIn("elapsed_minutes", patient.client.calls[0][1])

    def test_missing_vitals_never_become_deltas(self):
        state = SimpleNamespace(vital_signs={}, current_symptoms=[])
        event = DeteriorationModule()._apply_effect(state, {"spo2_delta": -2, "new_symptoms": ["breathlessness"]},
                                                  event_type="test", reason="test")
        self.assertEqual(state.vital_signs, {})
        self.assertEqual(state.current_symptoms, ["breathlessness"])
        self.assertEqual(len(event["data_gaps"]), 1)

    def test_relative_time_and_once_only(self):
        source = case()
        source["temporal_profile"]["arrival_time_min"] = 20
        scheduler = HospitalParallelScheduler()
        state = scheduler.initialize([source])
        scheduler.run_until(state, 21)
        self.assertEqual(state.case("llm-test").vital_signs["spo2"], 98)
        scheduler.run_until(state, 24)
        self.assertEqual(state.case("llm-test").vital_signs["spo2"], 96)
        self.assertEqual(len(state.case("llm-test").deterioration_events), 1)

    def test_configured_intervention_changes_state_and_suppresses_matching_trigger(self):
        source = case()
        source["temporal_profile"]["interventions"] = {"synthetic_support": {
            "delay_minutes": 1, "effect": {"spo2_delta": 1, "resolved_symptoms": ["breathlessness"]}}}
        source["temporal_profile"]["deterioration_model"] = {"triggers": [{
            "if_unaddressed_for_minutes": 6, "addressed_by": "synthetic_support", "effect": {"spo2_delta": -4}}]}
        _, state, _ = self.run_case([decision("treat", "synthetic_support"),
            decision("ask_patient", "How are you now?"), '{"fact_ids":["current:0"],"unknown":false}',
            decision("diagnose", "unresolved", certainty="unresolved")], source, max_decisions=3)
        runtime = state.case("llm-test")
        self.assertEqual(runtime.vital_signs["spo2"], 97)
        self.assertNotIn("breathlessness", runtime.current_symptoms)
        self.assertEqual(len(runtime.interventions), 1)

    def test_fixed_demo_progression_is_normalized_and_applied_once(self):
        from app.data.demo_scenario_loader import load_demo_scenario_cases
        cases, _ = load_demo_scenario_cases(Path("data/raw/er_multi_patient_simulation_scenario.json"))
        scheduler = HospitalParallelScheduler({"capacities": {"er_beds": 0}})
        state = scheduler.initialize(cases)
        scheduler.run_until(state, 32)
        runtime = state.case("P01")
        self.assertEqual(runtime.vital_signs["systolic_bp"], 96)
        self.assertEqual(runtime.vital_signs["oxygen_saturation"], 91)
        self.assertEqual(runtime.health_state, "Critical")
        self.assertEqual(runtime.first_deterioration_min, 15)
        self.assertEqual(len(runtime.deterioration_events), 2)
        self.assertIn("pale, dizzy, more dyspneic", runtime.current_symptoms)

    def test_missing_result_is_not_fabricated(self):
        from app.core.hospital_llm_policy import HospitalLLMPolicy
        source = case()
        source["hidden_test_results"] = {}
        runtime = HospitalParallelScheduler().initialize([source]).case("llm-test")
        self.assertEqual(HospitalLLMPolicy.build_objective_finding(runtime, "Blood Test"), "")
        self.assertEqual(HospitalLLMPolicy.build_test_result_summary(runtime, "Blood Test")["source"], "missing")

    def test_live_llm_mode_does_not_invent_consult_dialogue(self):
        from app.core.live_parallel_visual_runtime import LiveParallelVisualRuntimeWriter
        _, state, _ = self.run_case([decision("consult_specialty", "neurology"),
                                    decision("diagnose", "unresolved", certainty="unresolved")], max_decisions=2)
        writer = object.__new__(LiveParallelVisualRuntimeWriter)
        writer._last_dialogue_event_id = ""
        event = next(e for e in state.event_log if e["action"] == "consult_started")
        self.assertEqual(writer._dialogue_from_event(state, event)["lines"], [])

    def test_zero_minute_event_and_invalid_numeric_delta(self):
        source = case()
        source["temporal_profile"]["natural_history_events"][0]["minute"] = 0
        scheduler = HospitalParallelScheduler({"capacities": {"er_beds": 0}})
        state = scheduler.initialize([source])
        scheduler.run_until(state, 5)
        self.assertEqual(state.case("llm-test").vital_signs["spo2"], 96)
        source["temporal_profile"]["natural_history_events"][0]["changes"]["spo2_delta"] = float("nan")
        with self.assertRaises(ValueError):
            scheduler.initialize([source])

    def test_unresolved_department_label_is_not_a_diagnosis(self):
        _, state, _ = self.run_case([decision("diagnose", "general_medicine", certainty="unresolved")], max_decisions=1)
        runtime = state.case("llm-test")
        self.assertEqual(runtime.assessment_summary, "Unresolved presenting complaint: pain")
        final = next(e for e in state.event_log if e["event_type"] == "case_completed")
        self.assertEqual(final["rationale"], "Review the observed symptoms and evidence.")
        self.assertEqual(final["payload"]["diagnosis_status"], "unresolved")

    def test_absolute_vitals_keep_aliases_and_bp_consistent(self):
        runtime = SimpleNamespace(vital_signs={"spo2": 98, "oxygen_saturation": 98,
            "systolic_bp": 120, "diastolic_bp": 80, "blood_pressure": "120/80"}, current_symptoms=[])
        DeteriorationModule()._apply_effect(runtime, {"vital_values": {"oxygen_saturation": 95}, "sbp_delta": -5},
                                          event_type="test", reason="test")
        self.assertEqual(runtime.vital_signs["spo2"], 95)
        self.assertEqual(runtime.vital_signs["blood_pressure"], "115/80")


if __name__ == "__main__":
    unittest.main()
