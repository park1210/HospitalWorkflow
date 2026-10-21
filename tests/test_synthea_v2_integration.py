"""Small adversarial projection/boundary checks; no live model calls."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import result

from app.agents.patient_agent import PatientAgent
from app.core.agent_registry import AgentRegistry
from app.core.clinical_observation import encounter_evidence
from app.core.longitudinal_memory import PatientMemoryStore
from app.core.longitudinal_runner import run_longitudinal
from app.data.synthea_v2_adapter import convert_case
from app.scripts.run_synthea_v2_pilot import PilotBoundary, run_case

ROOT = Path(__file__).resolve().parents[1]


class V2IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (ROOT / "current_symptom_presentation_benchmark_v2.jsonl").open(encoding="utf-8") as f:
            cls.source = json.loads(next(f))
        cls.source["past_visits"] = cls.source["past_visits"][:1]
        cls.source["past_visits"][0]["records"] = cls.source["past_visits"][0]["records"][:2]
        cls.manifest = json.loads((ROOT / "app/data/challenge_v4/registry.json").read_text())

    def test_hidden_and_legacy_poison_cannot_change_input(self):
        before, trace = convert_case(self.source)
        altered = deepcopy(self.source)
        for key in ("evaluation", "current_symptom_provenance", "current_symptom_annotation", "patient_visible_state"):
            altered[key] = {"POISON_HIDDEN": "POISON_HIDDEN"}
        for symptom in altered["patient_visible_state_v2"]["current_symptoms"]:
            symptom.update(module="POISON_HIDDEN", cause="POISON_HIDDEN", evidence="POISON_HIDDEN", value=999999)
        after, altered_trace = convert_case(altered)
        self.assertEqual(before, after)
        self.assertEqual(trace, altered_trace)
        self.assertNotIn("POISON_HIDDEN", json.dumps(after))

    def test_grounded_names_and_unknown_detail(self):
        case, trace = convert_case(self.source)
        names = list(dict.fromkeys(s["symptom_name"] for s in self.source["patient_visible_state_v2"]["current_symptoms"]))
        self.assertEqual(trace["utterance"], "My symptoms are: " + ", ".join(names) + ".")
        agent = PatientAgent({"synthea_v2_patient_input": case["synthea_v2_patient_input"]})
        for question in ("When did it start?", "What is my diagnosis?", "What are my CT results?"):
            result = agent.answer_v2(question)
            self.assertTrue(result["unknown"])
            self.assertEqual(result["source_fact_ids"], [])

    def test_future_symptom_rejected(self):
        source = deepcopy(self.source)
        source["patient_visible_state_v2"]["current_symptoms"][0]["symptom_timestamp"] = "2099-01-01T00:00:00Z"
        with self.assertRaises(ValueError): convert_case(source)

    def test_future_memory_not_selected_source_preserved(self):
        source = deepcopy(self.source)
        source["past_visits"][0]["records"][0]["timestamp"] = "2099-01-01T00:00:00Z"
        case, _ = convert_case(source)
        self.assertEqual(case["source_past_visits"], source["past_visits"])
        store = PatientMemoryStore(r for v in case["past_visits"] for r in v["records"])
        result = store.retrieve(case["longitudinal"], "", "full_history")
        self.assertEqual(len(result["records"]), 1)

    def test_full_history_budget_no_selective_fallback_actual_binding(self):
        case, _ = convert_case(self.source)
        result = run_case(case, "full_history_budgeted", self.manifest,
                          SimpleNamespace(live=False, context_chars=1, memory_chars=30000, top_k=1))
        self.assertEqual(result["status"], "context_limit_exceeded")
        self.assertEqual(len(result["memory"]["records"]), 2)
        self.assertEqual(result["memory"]["mode"], "full_history")
        self.assertEqual(result["actual_llm_calls"], 0)
        
        trace = result["boundary_traces"][0]
        binding = result["binding"]
        if trace["role"] == "specialty":
            self.assertIsNotNone(binding)
            self.assertEqual(
                binding["model"],
                trace["model_binding"],
                )
        elif trace["role"] == "er":
    # No specialty binding is required if the ER
    # continues after routing abstention.
            self.assertIsNone(binding)

            registry = AgentRegistry(self.manifest)
            self.assertEqual(
                trace["model_binding"],
            registry.get("er")["model"],
            )

        else:
            self.fail(
                "Unexpected boundary role: " + str(trace["role"])
            )


    def test_unreleased_event_not_returned(self):
        runtime = SimpleNamespace(current_time_min=0, case_data={"current_encounter_events": [
            {"action": "Test", "target": "x", "available_minute": 10, "evidence": "hidden"}]})
        self.assertIsNone(encounter_evidence(runtime, "Test", "x"))
        runtime.current_time_min = 10
        self.assertEqual(encounter_evidence(runtime, "Test", "x")["evidence"], "hidden")

    def test_payload_metadata_guard(self):
        boundary = PilotBoundary(AgentRegistry(self.manifest))
        with self.assertRaises(AssertionError):
            boundary.chat_json("", json.dumps({"observation": {"evaluation": "poison"}}))
        self.assertEqual(boundary.calls, 0)

    def test_doctor_ask_calls_grounded_patient_in_real_loop(self):
        class AskThenStop:
            calls = 0

            def chat_json(self, system, prompt, model=None, schema=None):
                self.calls += 1
                if self.calls > 1:
                    raise RuntimeError("Test stops after observing patient answer")
                p = json.loads(prompt)
                c = next(c for c in p["candidate_actions"] if c["type"] == "Ask")
                return json.dumps({"action": c["action"], "target": c["target"],
                    "department": p["department"], "rationale": "Clarify available patient facts.",
                    "assessment": "Unresolved", "certainty": "unresolved",
                    "evidence_indices": [], "memory_ids": []})
        case, _ = convert_case(self.source)
        report = run_longitudinal([case], client=AskThenStop(), registry_manifest=self.manifest,
                                  routing_mode="adaptive", memory_source="fixed")
        runtime = next(iter(report["visits"][0]["final_state"]["cases"].values()))
        self.assertTrue(runtime["question_history"])
        groundings = [a["patient_grounding"] for a in runtime["llm_audit"] if "patient_grounding" in a]
        self.assertTrue(groundings)
        self.assertTrue(all(g["grounded"] for g in groundings))
        self.assertFalse(any(a["role"] == "patient" for a in runtime["llm_audit"]))


if __name__ == "__main__":
    unittest.main()
