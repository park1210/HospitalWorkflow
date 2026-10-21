"""Small source-boundary checks and three-case integration; no model/server calls."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from app.core.clinical_observation import prepare_encounter, encounter_evidence
from app.core.longitudinal_runner import run_longitudinal
from app.core.agent_registry import AgentRegistry

ROOT = Path(__file__).resolve().parents[1]


def inputs():
    cases = json.loads((ROOT / "app/data/encounter_pilot.json").read_text(encoding="utf-8"))
    registry = json.loads((ROOT / "app/data/challenge_v4/registry.json").read_text(encoding="utf-8"))
    return cases, registry


class ScriptedSpecialist:
    """Explicit test double, not a claim of real LLM quality."""
    def __init__(self):
        self.payloads = []

    def chat_json(self, system, prompt, model=None, schema=None):
        p = json.loads(prompt)
        self.payloads.append((model, p))
        candidates = p["candidate_actions"]
        candidate = next((c for kind in ("Ask", "Test", "Consult", "Diagnose")
                          for c in candidates if c["type"] == kind), None)
        assert candidate is not None
        return json.dumps({
            "action": candidate["action"], "target": candidate["target"] or "Unresolved",
            "department": p["department"], "rationale": "Use available source evidence, then terminate.",
            "assessment": "Pending source evidence", "certainty": "unresolved",
            "evidence_indices": [], "memory_ids": [],
        })


class EncounterPipelineTests(unittest.TestCase):
    def test_three_case_pipeline(self):
        cases, registry = inputs()
        client = ScriptedSpecialist()
        report = run_longitudinal(cases, mode="selective", top_k=1, minute_limit=60,
                                  registry_manifest=registry, routing_mode="adaptive",
                                  memory_source="fixed", initial_memory=[], client=client)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(len(report["visits"]), 3)
        self.assertTrue(client.payloads)
        self.assertTrue(all(p["role"] == "specialty" for _, p in client.payloads))
        self.assertIn("qwen-neurology:latest", {m for m, _ in client.payloads})
        self.assertIn("qwen-pulmonology:latest", {m for m, _ in client.payloads})
        for visit in report["visits"]:
            rt = next(iter(visit["final_state"]["cases"].values()))
            for call in rt["llm_audit"]:
                self.assertIn("candidate_actions", call)
                self.assertIn("selected_specialty", call["routing"])
            if visit["identity"]["patient_id"] == "encounter-p001":
                self.assertGreaterEqual(rt["test_results"][0]["observed_minute"], 8)
            if visit["identity"]["patient_id"] == "encounter-p003":
                self.assertEqual(rt["question_history"][0]["answer"], "The sensory symptoms started yesterday.")
                self.assertIn("No respiratory investigation", rt["consult_history"][0]["opinion"])
        first = client.payloads[0][1]
        self.assertNotIn("reduced sensation", json.dumps(first))
        self.assertNotIn("primary_specialty", json.dumps(first))

    def test_future_and_cross_patient_past_rejected(self):
        cases, _ = inputs()
        for field, value in (("available_at", "2027-01-01T00:00:00Z"), ("patient_id", "other")):
            c = deepcopy(cases[0])
            c["past_visits"][0]["records"][0][field] = value
            with self.assertRaises(ValueError):
                prepare_encounter(c)

    def test_event_release_and_missing(self):
        from types import SimpleNamespace
        cases, _ = inputs()
        rt = SimpleNamespace(case_data=prepare_encounter(cases[0]), current_time_min=0)
        self.assertIsNone(encounter_evidence(rt, "Test", "Focused neurologic examination"))
        rt.current_time_min = 8
        self.assertIsNotNone(encounter_evidence(rt, "Test", "Focused neurologic examination"))
        self.assertIsNone(encounter_evidence(rt, "Test", "invented"))

    def test_initial_fields_are_allowlisted(self):
        cases, _ = inputs()
        cases[0]["current_initial_state"]["final_diagnosis"] = "hidden"
        with self.assertRaises(ValueError):
            prepare_encounter(cases[0])

    def test_routing_does_not_use_gold_department(self):
        _, manifest = inputs()
        router = AgentRegistry(manifest)
        result = router.route({"chief_complaint": "respiratory breathing",
                               "primary_specialty": "neurology"}, ["neurology", "pulmonology"], mode="adaptive")
        self.assertEqual(result["selected_specialty"], "pulmonology")

    def test_cost_latency_do_not_change_selection(self):
        _, manifest = inputs()
        artifact = json.loads((ROOT / "app/data/challenge_v4/routing_utility.json").read_text(encoding="utf-8"))
        observation = {"chief_complaint": "focal sensory neurologic"}
        a = AgentRegistry(manifest, artifact).route(observation, ["neurology", "pulmonology"], mode="adaptive")
        altered = deepcopy(artifact)
        altered["weights"] = {"accuracy": 10, "cost": 999999, "latency": 999999}
        for sample in altered["samples"]:
            sample["cost"] = 999 if "neuro" in sample["agent_id"] else 0
            sample["latency_seconds"] = sample["cost"]
        b = AgentRegistry(manifest, altered).route(observation, ["neurology", "pulmonology"], mode="adaptive")
        self.assertEqual(a["specialty_scores"], b["specialty_scores"])
        self.assertEqual(a["selected_specialty"], b["selected_specialty"])

    def test_voi_runs_after_specialist_and_uses_source_candidates(self):
        cases, registry = inputs()
        case = cases[0]
        model = json.loads((ROOT / "app/data/voi_synthetic/model.json").read_text(encoding="utf-8"))
        case["past_visits"] = []
        case["current_encounter_events"] = [
            {"event_id": "t", "action": "Test", "target": "T", "available_minute": 0,
             "evidence": "Synthetic A finding"}]
        client = ScriptedSpecialist()
        report = run_longitudinal([case], mode="none", registry_manifest=registry,
                                  routing_mode="adaptive", memory_source="fixed",
                                  voi_model=model, client=client, minute_limit=60)
        self.assertEqual(report["status"], "completed")
        rt = next(iter(report["visits"][0]["final_state"]["cases"].values()))
        self.assertEqual(len(client.payloads), 2)
        self.assertEqual(rt["assessment_summary"], "Synthetic A")
        self.assertTrue(all(c["action_selector"] == "explicit_outcome_voi" for c in rt["llm_audit"]))
        self.assertEqual(rt["llm_audit"][0]["decision"]["target"], "T")
        self.assertIn("specialist_proposal", rt["llm_audit"][0])

    def test_expanded_semantic_query_requires_exact_saved_state(self):
        from app.core.embedding_builder import build_embeddings
        from app.core.memory_retrieval import MemoryEmbeddings
        from app.core.clinical_observation import memory_query, initial_symptoms
        from app.core.memory_evaluation import visit_key
        cases, _ = inputs()
        c = prepare_encounter(cases[0])
        records = c["past_visits"][0]["records"]
        state = {"chief_complaint": c["doctor_visible_info"]["chief_complaint"],
                 "vital_signs": {"spo2": 98}, "current_symptoms": initial_symptoms(c)}
        later = dict(state, objective_findings=["Released finding"])
        embeddings = MemoryEmbeddings(build_embeddings(records, [c], query_states=[later]))
        for obs in (state, later):
            self.assertIn(records[0]["memory_id"],
                          embeddings.scores(records, memory_query(obs), visit_key(c["longitudinal"])))
        with self.assertRaisesRegex(ValueError, "query embedding"):
            embeddings.scores(records, memory_query(dict(state, working_assessment="not saved")),
                              visit_key(c["longitudinal"]))


if __name__ == "__main__":
    unittest.main()
