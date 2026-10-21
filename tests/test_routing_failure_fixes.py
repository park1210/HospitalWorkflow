"""Reproduce the observed contract/limit failures without an Ollama server."""
import json
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from app.core.agent_registry import AgentRegistry
from app.core.longitudinal_runner import run_longitudinal
from app.core.specialty_router import LLMRouter
from app.llm.role_call import RoleCallError
from app.scripts.run_synthea_v2_pilot import PilotBoundary

ROOT = Path(__file__).resolve().parents[1]


class ScoreClient:
    def __init__(self, bad=70, always_bad=False):
        self.bad, self.always_bad = bad, always_bad
        self.payloads = []

    def chat_json(self, system, prompt, model=None, schema=None):
        p = json.loads(prompt)
        self.payloads.append(p)
        value = self.bad if self.always_bad or len(self.payloads) == 1 else 0.7
        return json.dumps({"selected_specialty": "neurology", "scores": {"neurology": value}, "rationale": "Fixture evidence."})


class FailureFixTests(unittest.TestCase):
    def test_score_repair_is_bounded_and_keeps_original_error(self):
        for bad in (70, "0.7", True, float("nan")):
            with self.subTest(bad=bad):
                client, audit = ScoreClient(bad), []
                result = LLMRouter(client, "fixture").select({}, ["neurology"], audit=audit)
                self.assertEqual(result["specialty_scores"], {"neurology": 0.7})
                self.assertEqual(len(audit), 2)
                self.assertEqual(audit[0]["status"], "error")
                self.assertIn("invalid_response", audit[0])
                self.assertEqual(audit[0]["validation_detail"]["field"], "scores.neurology")
                self.assertEqual(audit[1]["repair_of_audit_index"], 0)
                self.assertFalse(audit[1]["fallback_used"])
                self.assertIn("output_contract_repair", client.payloads[1])
        client, audit = ScoreClient(always_bad=True), []
        with self.assertRaises(RoleCallError):
            LLMRouter(client, "fixture").select({}, ["neurology"], audit=audit)
        self.assertEqual(len(audit), 2)
        self.assertEqual(audit[-1]["routing_result"]["status"], "failed")

    def test_same_public_router_payload_uses_cache_but_changes_invalidate_it(self):
        client, audit, cache = ScoreClient(), [], {}
        router = LLMRouter(client, "fixture")
        router.select({"chief_complaint": "a"}, ["neurology"], audit=audit, cache=cache)
        calls = len(client.payloads)
        cached = router.select({"chief_complaint": "a", "longitudinal_memory": {"records": []}},
                               ["neurology"], audit=audit, cache=cache)
        self.assertTrue(cached["cache_hit"])
        self.assertEqual(len(client.payloads), calls)
        router.select({"chief_complaint": "b"}, ["neurology"], audit=audit, cache=cache)
        self.assertEqual(len(client.payloads), calls + 1)
        aware = LLMRouter(client, "fixture", use_memory=True)
        state = {"chief_complaint": "b", "longitudinal_memory": {"records": [{"memory_id": "m", "text": "a"}]}}
        aware.select(state, ["neurology"], audit=audit, cache=cache)
        calls = len(client.payloads)
        state["longitudinal_memory"]["records"][0]["text"] = "changed"
        self.assertFalse(aware.select(state, ["neurology"], audit=audit, cache=cache)["cache_hit"])
        self.assertEqual(len(client.payloads), calls + 1)

    def test_separate_budgets_allow_ninth_combined_call_and_enforce_role_limit(self):
        manifest = json.loads((ROOT / "app/data/challenge_v4/registry.json").read_text())
        boundary = PilotBoundary(AgentRegistry(manifest), live=True)
        router_payload = json.dumps({"current_state": {}, "candidate_specialties": ["neurology"]})
        clinical_payload = json.dumps({"observation": {}, "role": "specialty"})
        with patch("app.llm.ollama_client.OllamaClient") as client:
            client.return_value.chat_json.return_value = "{}"
            for _ in range(4):
                boundary.chat_json("", router_payload)
                boundary.chat_json("", clinical_payload)
            boundary.chat_json("", router_payload)
            self.assertEqual(boundary.calls, 9)
            for _ in range(3): boundary.chat_json("", router_payload)
            with self.assertRaises(RuntimeError): boundary.chat_json("", router_payload)
        self.assertEqual(boundary.call_counts, {"router": 8, "clinical": 4})
        self.assertEqual(boundary.traces[-1]["limit_type"], "router")

    def test_department_diagnosis_repair_in_actual_loop(self):
        case = json.loads((ROOT / "app/data/encounter_pilot.json").read_text())[0]
        manifest = json.loads((ROOT / "app/data/challenge_v4/registry.json").read_text())
        class ClinicalClient:
            def chat_json(self, system, prompt, model=None, schema=None):
                p = json.loads(prompt)
                indices = p["supported_diagnosis_eligible_indices"]
                row = {"department": p["department"], "rationale": "Use the released fixture evidence.",
                       "assessment": "Fixture only", "evidence_indices": [], "memory_ids": [], "certainty": "unresolved"}
                if indices and "diagnose" in p["allowed_actions"]:
                    row.update(action="diagnose", target="Fixture diagnosis" if "output_contract_repair" in p else p["department"],
                               certainty="supported", evidence_indices=[indices[0]])
                else:
                    action = next(c for c in p["candidate_actions"] if c["type"] == "Test")
                    row.update(action=action["action"], target=action["target"])
                return json.dumps(row)
        result = run_longitudinal([case], registry_manifest=manifest, client=ClinicalClient(), memory_source="fixed")
        self.assertEqual(result["status"], "completed")
        runtime = next(iter(result["visits"][0]["final_state"]["cases"].values()))
        failures = [a for a in runtime["llm_audit"] if a["status"] == "error"]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["validation_detail"]["code"], "diagnosis_is_department")
        self.assertIn("repaired_by_audit_index", failures[0])
        self.assertEqual(runtime["voi_state"]["initial_primary_routing"]["status"], "available")

    def test_network_errors_are_not_retried(self):
        class Offline:
            calls = 0
            def chat_json(self, *args, **kwargs):
                self.calls += 1
                raise TimeoutError("Test timeout")
        client, audit = Offline(), []
        with self.assertRaises(RoleCallError):
            LLMRouter(client, "fixture").select({}, ["neurology"], audit=audit)
        self.assertEqual(client.calls, 1)
        self.assertEqual(audit[0]["failure_category"], "timeout")
        self.assertNotIn("invalid_response", audit[0])


if __name__ == "__main__":
    unittest.main()
