"""Router plumbing with scripted responses only: no server/model experiment."""
from copy import deepcopy
import json
import io
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.core.agent_registry import AgentRegistry
from app.core.longitudinal_runner import run_longitudinal
from app.core.specialty_router import LLMRouter
from app.data.synthea_v2_adapter import convert_case
from app.llm.prompt_loader import specialty_system_prompt
from app.llm.role_call import RoleCallError
from app.scripts.run_synthea_v2_pilot import run_case, evaluate
from app.scripts.run_synthea_v2_pilot import main as pilot_main

ROOT = Path(__file__).resolve().parents[1]


class ScriptedClient:
    def __init__(self, fail_router=False):
        self.payloads = []
        self.fail_router = fail_router

    def chat_json(self, system, prompt, model=None, schema=None):
        p = json.loads(prompt)
        self.payloads.append((model, p))
        if "candidate_specialties" in p:
            if self.fail_router:
                return "not JSON"
            return json.dumps({"selected_specialty": "otolaryngology",
                "scores": {d: 0.9 if d == "otolaryngology" else 0.1 for d in p["candidate_specialties"]},
                "rationale": "Use the supplied current presentation."})
        # Exercise an actual clinical decision after routing, using a test double.
        c = next((c for c in p["candidate_actions"] if c["type"] == "Ask"), None)
        if c is None:
            raise RuntimeError("Scripted test stops after available questions")
        return json.dumps({"action": c["action"], "target": c["target"],
            "department": p["department"], "rationale": "Clarify a source-backed patient fact.",
            "assessment": "Unresolved", "certainty": "unresolved",
            "evidence_indices": [], "memory_ids": []})


class PrimaryRouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ROOT / "app/data/synthea_v2/registry_shared_qwen.json").read_text())
        with (ROOT / "current_symptom_presentation_benchmark_v2.jsonl").open(encoding="utf-8") as f:
            cls.source = json.loads(next(f))
        cls.source["past_visits"] = cls.source["past_visits"][:1]
        cls.source["past_visits"][0]["records"] = cls.source["past_visits"][0]["records"][:2]
        cls.case, _ = convert_case(cls.source)
        # Fixture text forces nonempty retrieval without adding a production algorithm.
        cls.case["past_visits"][0]["records"][0]["text"] += " Sore Throat"

    def args(self, router, live=False):
        return SimpleNamespace(primary_router=router, live=live, context_chars=60000,
                               memory_chars=30000, top_k=5)

    def test_prompt_import_and_shared_bindings(self):
        self.assertTrue(specialty_system_prompt("otolaryngology"))
        self.assertEqual({a["model"] for a in self.manifest["agents"]}, {"qwen2.5:1.5b-instruct"})

    def test_rule_result_is_runtime_result(self):
        result = run_case(self.case, "no_memory", self.manifest, self.args("rule_similarity"))
        self.assertEqual(result["routing"]["router"], "RuleSimilarityRouter")
        self.assertEqual(result["routing_result_source"], "runtime")
        self.assertEqual(result["router_audit"], [])
        self.assertTrue(result["specialty_boundary_reached"])

    def test_live_path_for_both_llm_routers_with_scripted_client(self):
        for mode, label in (("llm", "LLMRouter"), ("memory_aware_llm", "MemoryAwareLLMRouter")):
            with self.subTest(mode=mode):
                client = ScriptedClient()
                with patch("app.llm.ollama_client.OllamaClient", return_value=client):
                    result = run_case(self.case, "selective", self.manifest, self.args(mode, True))
                self.assertEqual(result["routing"]["router"], label)
                self.assertEqual(result["routing_result_source"], "runtime")
                self.assertEqual(result["binding"]["department"], "otolaryngology")
                self.assertTrue(result["specialty_boundary_reached"])
                rt = next(iter(result["live_final_state"]["cases"].values()))
                self.assertEqual(rt["voi_state"]["primary_routing"]["router"], label)
                self.assertTrue(rt["question_history"])  # Router calls did not consume clinical action budget.
                for model, payload in client.payloads:
                    self.assertEqual(model, "qwen2.5:1.5b-instruct")
                    if "candidate_specialties" in payload:
                        self.assertEqual("retrieved_memory" in payload, mode == "memory_aware_llm")
                        self.assertNotIn("longitudinal_memory", payload["current_state"])
                        if mode == "memory_aware_llm":
                            self.assertTrue(payload["retrieved_memory"])
                        for hidden in ("evaluation", "primary_specialty", "gold_condition_description"):
                            self.assertNotIn(hidden, json.dumps(payload))
                self.assertEqual(result["router_audit"][0]["routing_result"]["router"], label)
                saved = json.loads(json.dumps(evaluate([result], {self.case["case_id"]: self.source})))
                self.assertEqual(saved["results"][0]["routing"]["router"], label)

    def test_offline_llm_stops_at_router_without_rule_fallback(self):
        for mode in ("llm", "memory_aware_llm"):
            result = run_case(self.case, "selective", self.manifest, self.args(mode))
            self.assertEqual(result["status"], "stopped_before_model_call")
            self.assertEqual(result["routing"]["status"], "failed")
            self.assertIsNone(result["binding"])
            self.assertFalse(result["specialty_boundary_reached"])
            self.assertEqual(result["actual_llm_calls"], 0)
            trace = result["boundary_traces"][0]
            self.assertEqual(trace["role"], "router")
            self.assertIsNone(trace["memory_query"])
            self.assertIsNone(trace["requested_selector"])
            self.assertEqual(trace["router_uses_memory"], mode == "memory_aware_llm")

    def test_failed_router_preserved_no_specialty_call(self):
        client = ScriptedClient(fail_router=True)
        with patch("app.llm.ollama_client.OllamaClient", return_value=client):
            result = run_case(self.case, "no_memory", self.manifest, self.args("llm", True))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["routing"]["router"], "LLMRouter")
        self.assertEqual(result["routing"]["status"], "failed")
        self.assertEqual(len(client.payloads), 1)
        self.assertIsNone(result["binding"])

    def test_router_allowlist_and_invalid_scores(self):
        client = ScriptedClient()
        audit = []
        LLMRouter(client, "test").select({"chief_complaint": "sore throat", "evaluation": "SECRET",
            "primary_specialty": "SECRET", "gold_condition_description": "SECRET",
            "longitudinal_memory": {"records": [{"text": "SECRET"}]}}, ["otolaryngology"], audit=audit)
        self.assertNotIn("SECRET", json.dumps(client.payloads))
        class BadScores:
            def chat_json(self, *args, **kwargs):
                return '{"selected_specialty":"otolaryngology","scores":{},"rationale":"test"}'
        with self.assertRaises(RoleCallError):
            LLMRouter(BadScores(), "test").select({}, ["otolaryngology"], audit=[])

    def test_configuration_changes_signature_and_rejects_invalid_mode(self):
        signatures = set()
        for mode in ("rule_similarity", "llm", "memory_aware_llm"):
            report = run_longitudinal([self.case], registry_manifest=self.manifest, memory_source="fixed",
                                      client=ScriptedClient(fail_router=True), primary_router=mode)
            self.assertEqual(report["routing_config"]["primary_router"], mode)
            signatures.add(report["resume_signature"])
        self.assertEqual(len(signatures), 3)
        with self.assertRaises(ValueError):
            run_longitudinal([], primary_router="invalid")

    def test_cli_saved_json_reports_requested_router_without_fallback(self):
        def small_case(source):
            case = deepcopy(self.case)
            case["case_id"] = source["case_id"]
            return case, {"grounded": True, "method": "test_fixture"}
        for mode, name in (("rule_similarity", "RuleSimilarityRouter"),
                           ("llm", "LLMRouter"), ("memory_aware_llm", "MemoryAwareLLMRouter")):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                out = Path(folder) / "results"
                argv = ["pilot", "--primary-router", mode, "--context-chars", "60000",
                        "--memory-chars", "30000", "--output-dir", str(out),
                        "--source", str(ROOT / "current_symptom_presentation_benchmark_v2.jsonl"),
                        "--registry", str(ROOT / "app/data/synthea_v2/registry_shared_qwen.json"),
                        "--candidate-report", str(ROOT / "final_task_candidate_report_v2.md")]
                with patch("sys.argv", argv), patch("app.scripts.run_synthea_v2_pilot.convert_case", side_effect=small_case), redirect_stdout(io.StringIO()):
                    pilot_main()
                validation = json.loads((out / "validation.json").read_text(encoding="utf-8"))
                self.assertEqual(validation["primary_router"], mode)
                self.assertEqual(validation["actual_llm_calls"], 0)
                results = json.loads((out / "routing_pilot_results.json").read_text(encoding="utf-8"))["results"]
                self.assertEqual(len(results), 20)
                self.assertEqual({r["routing"]["router"] for r in results}, {name})
                if mode != "rule_similarity":
                    self.assertTrue(all(r["evaluation"]["strict_correct"] is None for r in results))


if __name__ == "__main__":
    unittest.main()
