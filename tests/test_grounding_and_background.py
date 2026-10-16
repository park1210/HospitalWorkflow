import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
import unittest

from app.core.patient_facts import patient_facts, facts_for_question, render_selection
from app.core.background_stepper import BackgroundStepper
from app.core.clinical_preflight import clinical_preflight
from app.core.hospital_parallel_scheduler import HospitalParallelScheduler
from app.core.live_parallel_visual_runtime import LiveParallelVisualRuntimeWriter
from app.llm.role_call import progress_listener
from app.agents.patient_agent import PatientAgent


class GroundingTests(unittest.TestCase):
    def test_onset_selects_timing_and_missing_medication_remains_unknown(self):
        facts = patient_facts({"history": "Pain started today. Pain is mild.", "current_symptoms": ["pain"]})
        self.assertEqual([f["text"] for f in facts_for_question(facts, "When did it start?")], ["Pain started today."])
        self.assertEqual(facts_for_question(facts, "What medications are you taking?"), [])
    def test_clinician_query_gets_no_facts_and_activity_is_not_ct(self):
        class Client:
            def chat(self, system, user, model=None):
                self.payload = json.loads(user)
                return '{"fact_ids":[],"unknown":true}'
        patient = PatientAgent({"patient_visible_info": {"history": "Some recorded history."}})
        patient.client = Client()
        self.assertFalse(patient._is_clinician_only_question("Does activity make it worse?"))
        patient.answer("What is the CT result?", required=True)
        self.assertEqual(patient.client.payload["facts"], [])

    def test_current_question_does_not_offer_old_symptoms(self):
        class Client:
            def chat(self, system, user, model=None):
                self.payload = json.loads(user)
                return '{"fact_ids":["current:0"],"unknown":false}'
        patient = PatientAgent({"patient_visible_info": {"history": "Earlier pain."}})
        patient.client = Client()
        state = SimpleNamespace(current_symptoms=["breathlessness"], llm_audit=[])
        answer = patient.answer("How do you feel now?", state, required=True)
        self.assertTrue(all(f["scope"] == "current" for f in patient.client.payload["facts"]))
        self.assertNotIn("Earlier pain", answer)
        self.assertEqual(state.llm_audit[0]["grounding"]["selection"]["fact_ids"], ["current:0"])

    def test_extractive_negation_and_no_extra_time(self):
        facts = patient_facts({"history": "Pain started today. I do not take medication.", "current_symptoms": ["pain"]})
        answer = render_selection('{"fact_ids":["history:0","history:1"],"unknown":false}', facts)
        self.assertEqual(answer, "Pain started today. I do not take medication.")
        self.assertNotIn("morning", answer)

    def test_prose_forged_references_and_inconsistent_unknown_rejected(self):
        facts = patient_facts({"history": "Started today."})
        for raw in ['{"answer":"Started at 8am","fact_ids":["history:0"],"unknown":false}',
                    '{"fact_ids":["hidden_test:0"],"unknown":false}',
                    '{"fact_ids":["history:0"],"unknown":true}',
                    '{"fact_ids":[],"unknown":false}',
                    '{"fact_ids":["history:0","history:0"],"unknown":false}']:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                render_selection(raw, facts)

    def test_missing_and_resolved_symptoms_not_in_current_facts(self):
        before = patient_facts({"current_symptoms": ["breathlessness"]})
        after = patient_facts({"current_symptoms": []})
        self.assertTrue(before)
        self.assertEqual(after, [])
        self.assertEqual(render_selection('{"fact_ids":[],"unknown":true}', after), "I am not sure about that.")

    def test_preflight_does_not_fill_data_or_call_models(self):
        case = {"case_id": "missing", "available_tests": ["T"], "temporal_profile": {
            "deterioration_model": {"triggers": [{"effect": {"spo2_delta": -2}}]}}}
        original = copy.deepcopy(case)
        result = clinical_preflight([case])
        codes = {g["code"] for g in result["cases"][0]["gaps"]}
        self.assertTrue({"missing_test_result", "missing_initial_delta_baseline", "missing_intervention_response"} <= codes)
        self.assertEqual(case, original)
        self.assertEqual(result["llm_calls"], 0)
        self.assertEqual(result["clinical_validation"], "not_performed")


class BackgroundTests(unittest.TestCase):
    def test_waiting_never_exposes_partial_worker_state(self):
        gate = Event()
        class Scheduler:
            def step(self, state):
                state.current_minute = 99
                progress_listener.get()({"role": "patient", "status": "started"})
                if not gate.wait(2):
                    raise RuntimeError("Test gate timeout")
                state.current_minute = 1
        state = SimpleNamespace(current_minute=0)
        pulses = []
        def on_wait(progress):
            self.assertEqual(state.current_minute, 0)
            pulses.append(progress)
            gate.set()
        with BackgroundStepper(Scheduler(), heartbeat_seconds=0.01) as stepper:
            result = stepper.step(state, on_wait)
        self.assertEqual(result.current_minute, 1)
        self.assertEqual(state.current_minute, 0)
        self.assertEqual(pulses[0]["role"], "patient")

    def test_worker_failure_keeps_last_commit_and_exposes_failure_for_audit(self):
        class Scheduler:
            def step(self, state):
                state.current_minute = 3
                raise TimeoutError("worker failure")
        original = SimpleNamespace(current_minute=0)
        with BackgroundStepper(Scheduler(), heartbeat_seconds=0.01) as stepper:
            with self.assertRaises(TimeoutError) as failure:
                stepper.step(original, lambda _: None)
        self.assertEqual(original.current_minute, 0)
        self.assertEqual(failure.exception.failed_state.current_minute, 3)

    def test_heartbeat_does_not_create_replay_frame_or_repeat_dialogue(self):
        with TemporaryDirectory() as directory:
            writer = object.__new__(LiveParallelVisualRuntimeWriter)
            writer.history = [{"current_time_min": 7, "dialogue": {"lines": ["old"]}}]
            writer.snapshot_path = Path(directory) / "state.json"
            writer.on_inference_wait({"role": "er", "wall_wait_seconds": 2})
            payload = json.loads(writer.snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["simulation_status"], "waiting_for_model")
            self.assertEqual(payload["current_time_min"], 7)
            self.assertEqual(payload["dialogue"]["lines"], [])
            self.assertEqual(writer.history, [{"current_time_min": 7, "dialogue": {"lines": ["old"]}}])
            writer.on_inference_wait({"error_type": "RoleCallError"}, failed=True)
            self.assertEqual(json.loads(writer.snapshot_path.read_text(encoding="utf-8"))["simulation_status"], "failed")

    def test_background_demo_matches_synchronous_engine(self):
        cases = [{"case_id": "P", "doctor_visible_info": {"chief_complaint": "synthetic"}}]
        direct = HospitalParallelScheduler()
        background = HospitalParallelScheduler()
        left, right = direct.initialize(cases), background.initialize(cases)
        with BackgroundStepper(background) as stepper:
            for _ in range(30):
                direct.step(left)
                right = stepper.step(right, lambda _: None)
                self.assertEqual(left.snapshot(), right.snapshot())
                if not left.active_case_ids():
                    break


if __name__ == "__main__":
    unittest.main()
