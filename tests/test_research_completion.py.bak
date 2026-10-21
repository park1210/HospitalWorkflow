from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from io import BytesIO

from test_agent_registry import manifest, ModelsClient
from test_memory_research import case, replies
from test_longitudinal_memory import record, IDENTITY
from test_diagnostic_gate import Client, response
from app.core.agent_registry import AgentRegistry
from app.core.routing_utility import fit_utility, RoutingUtility
from app.core.routing_evaluation import evaluate_routing, decisions_from_outcomes
from app.core.longitudinal_runner import run_longitudinal, run_with_recovery
from app.core.memory_conflicts import assertion, detect_conflicts
from app.core.embedding_builder import build_embeddings
from app.core.memory_retrieval import MemoryEmbeddings
from app.core.longitudinal_memory import PatientMemoryStore
from app.core.research_dataset import synthetic_bundle, validate_bundle
from app.core.call_costs import summarize_costs
from app.core.routing_collection import collect_outcomes
from app.llm.role_call import role_call, response_usage, RoleCallError


def training():
    return [{"split": "train", "patient_id": "train-p", "decision_id": str(i),
             "agent_id": agent, "observation": {"chief_complaint": "synthetic discomfort"},
             "correct": agent == "neuro", "cost": .1, "latency_seconds": 1}
            for i in range(2) for agent in ("neuro", "cardio")]


class ResearchCompletionTests(unittest.TestCase):
    def test_adaptive_selects_utility_winner_without_gold(self):
        registry = AgentRegistry(manifest())
        artifact = fit_utility(training(), registry)
        registry = AgentRegistry(manifest(), artifact)
        result = registry.route({"chief_complaint": "synthetic discomfort", "gold_label": "cardio"},
                                ["cardiology", "neurology"], mode="adaptive")
        self.assertEqual(result["allowed_departments"], ["neurology"])
        self.assertGreater(result["utility_estimates"]["neurology"]["estimated_correct"], .5)

    def test_cold_start_preserves_options(self):
        registry = AgentRegistry(manifest(), fit_utility(training(), AgentRegistry(manifest())))
        result = registry.route({"chief_complaint": "unseen"}, ["neurology", "cardiology"], mode="adaptive")
        self.assertEqual(result["allowed_departments"], ["cardiology", "neurology"])

    def test_weights_change_choice(self):
        rows = training()
        for r in rows:
            r["cost"] = 10 if r["agent_id"] == "neuro" else 0
        registry = AgentRegistry(manifest(), fit_utility(rows, AgentRegistry(manifest()), weights={"accuracy": 1, "cost": 1, "latency": 0}))
        self.assertEqual(registry.route({"chief_complaint": "synthetic"}, ["neurology", "cardiology"], mode="adaptive")["allowed_departments"], ["cardiology"])

    def test_training_rejects_leakage_missing_comparators_and_unknown_cost(self):
        for edit in (lambda r: r[0].update(split="test"), lambda r: r.pop(), lambda r: r[0].update(cost=None)):
            rows = training()
            edit(rows)
            with self.assertRaises(ValueError):
                fit_utility(rows, AgentRegistry(manifest()))

    def test_evaluation_patient_overlap_rejected_before_calls(self):
        data = case()
        data["longitudinal"]["patient_id"] = "train-p"
        with self.assertRaises(ValueError):
            run_longitudinal([data], registry_manifest=manifest(), routing_mode="adaptive",
                             routing_utility=fit_utility(training(), AgentRegistry(manifest())), client=Client())

    def test_adaptive_real_scheduler_uses_specialist(self):
        client = ModelsClient(response("request_test", target="T"), response("consult_specialty", target="neurology"), response(certainty="supported", indices=[0]))
        result = run_longitudinal([case()], registry_manifest=manifest(), routing_mode="adaptive",
                                 routing_utility=fit_utility(training(), AgentRegistry(manifest())), client=client)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(client.models[-1], "test-neuro")
        self.assertEqual(len(client.models), 3)

    def test_regret_and_missing_counterfactuals(self):
        utility = RoutingUtility(fit_utility(training(), AgentRegistry(manifest())), AgentRegistry(manifest()))
        decision = {"patient_id": "test-p", "decision_id": "1", "candidate_agent_ids": ["neuro", "cardio"],
                    "chosen_agent_id": "cardio", "outcomes": {agent: {"correct": agent == "neuro", "cost": 0, "latency_seconds": 1} for agent in ("neuro", "cardio")}}
        self.assertEqual(evaluate_routing([decision], utility)["mean_regret"], 1)
        decision["outcomes"].pop("neuro")
        self.assertIsNone(evaluate_routing([decision], utility)["mean_regret"])

    def test_heldout_collection_converts_to_regret_without_oracle_in_router(self):
        registry = AgentRegistry(manifest(), fit_utility(training(), AgentRegistry(manifest())))
        rows = deepcopy(training()[:2])
        for row in rows:
            row.update(patient_id="heldout", split="test")
        decisions = decisions_from_outcomes(rows, registry)
        self.assertEqual(decisions[0]["chosen_agent_id"], "neuro")
        self.assertEqual(evaluate_routing(decisions, registry.utility)["mean_regret"], 0)
        rows[1]["observation"]["chief_complaint"] = "different"
        with self.assertRaises(ValueError):
            decisions_from_outcomes(rows, registry)

    def test_abstention_has_missing_regret(self):
        registry = AgentRegistry(manifest(), fit_utility(training(), AgentRegistry(manifest())))
        rows = deepcopy(training()[:2])
        for row in rows:
            row.update(patient_id="heldout", split="test", observation={"chief_complaint": "unseen"})
        result = evaluate_routing(decisions_from_outcomes(rows, registry), registry.utility)
        self.assertIsNone(result["mean_regret"])
        self.assertEqual(result["coverage"], 0)

    def test_resume_preserves_completed_visit_and_restarts_failed_only(self):
        first, second = case(), case()
        second["case_id"] = "next"
        second["longitudinal"].update(visit_id="v3", started_at="2026-03-01T00:00:00Z")
        failed = run_longitudinal([first, second], client=Client(*replies(), "bad json"))
        self.assertEqual(failed["committed_count"], 1)
        client = Client(*replies())
        resumed = run_longitudinal([first, second], client=client, resume_report=failed)
        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(resumed["visits"][0], failed["visits"][0])
        self.assertEqual(len(resumed["discarded_attempts"]), 1)
        self.assertEqual(len(client.payloads), 2)
        self.assertEqual(resumed["call_costs"]["failed_calls"], 1)

    def test_bounded_automatic_retry_and_changed_contract(self):
        snapshots = []
        report = run_with_recovery([case()], client=Client("bad", *replies()), max_retries=1, checkpoint_callback=lambda r: snapshots.append(deepcopy(r)))
        self.assertEqual(report["status"], "completed")
        self.assertTrue(snapshots)
        with self.assertRaises(ValueError):
            run_longitudinal([case()], client=Client(), mode="summary", resume_report=report)

    def test_retry_exhaustion_retains_every_failed_attempt(self):
        result = run_with_recovery([case()], client=Client("bad", "bad", "bad"), max_retries=2)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["committed_count"], 0)
        self.assertEqual(result["call_costs"]["failed_calls"], 3)
        self.assertEqual(len(result["discarded_attempts"]), 2)

    def test_corrupt_checkpoint_rejected(self):
        report = run_longitudinal([case()], client=Client("bad"))
        report["memory"]["records"].append(record())
        with self.assertRaisesRegex(ValueError, "integrity"):
            run_longitudinal([case()], client=Client(), resume_report=report)

    def test_native_probe_cpu_and_usage_schema(self):
        from app.llm.ollama_probe_client import OllamaProbeClient
        payload = {"prompt_eval_count": 4, "eval_count": 6, "message": {"content": '{"x": 1}'}}
        audit = []
        with patch("app.llm.ollama_probe_client.urlopen", return_value=BytesIO(json.dumps(payload).encode())) as request:
            result = role_call(OllamaProbeClient("http://localhost:11434", cpu=True), role="specialty", model="test",
                               system="s", payload={}, audit=audit, validate=json.loads, schema={"type": "object"})
            body = json.loads(request.call_args[0][0].data)
        self.assertEqual(body["options"]["num_gpu"], 0)
        self.assertEqual(body["format"], {"type": "object"})
        self.assertEqual(audit[0]["usage"]["total_tokens"], 10)
        self.assertEqual(result, {"x": 1})

    def test_explicit_conflict_candidate_preserves_both_and_excludes_superseded(self):
        rows = [record(text="Patient reports discomfort"), record("new", text="Patient denies discomfort")]
        self.assertEqual(len(detect_conflicts(rows)), 1)
        rows[0]["status_as_of_visit"] = "superseded"
        self.assertEqual(detect_conflicts(rows), [])
        self.assertIsNone(assertion("Patient reports no discomfort and cough"))
        self.assertEqual(assertion("기침 없음"), ("기침", False))

    def test_vectors_generated_and_texts_deduplicated(self):
        calls = []
        artifact = build_embeddings([record()], [case()], embed=lambda texts: calls.append(texts) or [[1, 2] for _ in texts])
        MemoryEmbeddings(artifact)
        self.assertEqual(len(calls), 1)
        artifact = build_embeddings([record()], [case()])
        query = case()["doctor_visible_info"]["chief_complaint"]
        rows = PatientMemoryStore([record()]).retrieve(IDENTITY, query, "semantic", embeddings=MemoryEmbeddings(artifact))
        self.assertEqual(rows["selected_count"], 1)
        self.assertEqual(len(artifact["records"]["old"]["vector"]), 256)

    def test_synthetic_bundle_temporal_labels_and_patient_split(self):
        template = json.loads(Path("app/data/longitudinal_synthetic.example.json").read_text(encoding="utf-8"))
        bundle = synthetic_bundle(template)
        self.assertEqual(validate_bundle(bundle)["visits"], 12)
        self.assertEqual(validate_bundle(bundle)["clinical_validation"], "unreviewed")
        bundle["splits"]["test"].append(bundle["splits"]["train"][0])
        with self.assertRaises(ValueError):
            validate_bundle(bundle)

    def test_bundle_future_labels_and_unsupported_review_claim_rejected(self):
        template = json.loads(Path("app/data/longitudinal_synthetic.example.json").read_text(encoding="utf-8"))
        bundle = synthetic_bundle(template)
        key = next(iter(bundle["annotations"]))
        bundle["annotations"][key]["relevant_memory_ids"] = ["synthetic-patient-0-memory-1"]
        with self.assertRaises(ValueError):
            validate_bundle(bundle)
        bundle = synthetic_bundle(template)
        bundle["provenance"]["review_status"] = "expert_reviewed"
        with self.assertRaises(ValueError):
            validate_bundle(bundle)

    def test_usage_retained_on_validation_failure_and_reset(self):
        class UsageClient:
            def chat(self, *args, **kwargs):
                response_usage.set({"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
                return "invalid"
        audit = []
        with self.assertRaises(RoleCallError):
            role_call(UsageClient(), role="er", model="m", system="", payload={}, audit=audit, validate=json.loads)
        costs = summarize_costs(audit, {"m": {"input_per_million": 1, "output_per_million": 2, "currency": "USD"}})
        self.assertAlmostEqual(costs["total_cost"], .00002)
        self.assertEqual(costs["failed_calls"], 1)
        self.assertIsNone(response_usage.get())

    def test_unknown_usage_is_not_zero_and_probe_hides_gold(self):
        client = Client(json.dumps({"diagnosis": "x", "rationale": "evidence"}), json.dumps({"diagnosis": "x", "rationale": "evidence"}))
        probes = [{"patient_id": "train-p", "decision_id": "d", "split": "train", "expected_diagnoses": ["x"],
                   "observation": {"chief_complaint": "synthetic", "gold_label": "secret"}}]
        rows = collect_outcomes(probes, AgentRegistry(manifest()), client, {})
        self.assertIsNone(rows[0]["cost"])
        self.assertNotIn("secret", json.dumps(client.payloads))
        self.assertTrue(rows[0]["correct"])


if __name__ == "__main__":
    unittest.main()
