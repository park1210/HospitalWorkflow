import json
from pathlib import Path
import unittest

from app.llm.role_call import role_call, RoleCallError, response_metadata, response_usage
from app.core.longitudinal_runner import run_longitudinal


class TruncatedClient:
    def chat(self, *args, **kwargs):
        response_metadata.set({"finish_reason": "length", "output_characters": 1})
        response_usage.set({"prompt_tokens": 10, "completion_tokens": 768, "total_tokens": 778})
        return "{"


class CompactClient:
    def __init__(self):
        self.payloads = []
        self.saw_consult_schema = False

    def chat_json(self, system, user, model=None, schema=None):
        payload = json.loads(user)
        self.payloads.append(payload)
        branches = schema.get("anyOf", [schema])
        for branch in branches:
            self_check = branch["properties"]
            assert self_check["rationale"]["maxLength"] == 240
            assert self_check["evidence_indices"]["maxItems"] <= 4
            action = self_check["action"]["enum"]
            assert len(action) == 1
            if action[0] == "consult_specialty":
                assert self_check["target"]["enum"] == payload["available_departments"]
                self.saw_consult_schema = True
            if action[0] == "request_test":
                assert self_check["target"]["enum"] == payload["available_tests"]
        evidence = payload["supported_diagnosis_eligible_indices"]
        label = None
        if evidence:
            finding = payload["evidence"][evidence[0]]
            label = next(d for d in payload["diagnosis_catalog"] if d in finding)
        return json.dumps({"action": "diagnose" if label else "request_test", "target": label or "T",
                           "rationale": "Released evidence supports this action.", "assessment": label or "Need objective evidence.",
                           "department": "general_medicine", "certainty": "supported" if label else "unresolved",
                           "evidence_indices": evidence[:1] if label else [], "memory_ids": []})


class OutputContractTests(unittest.TestCase):
    def test_truncation_records_usage_and_restores_context(self):
        audit = []
        with self.assertRaises(RoleCallError):
            role_call(TruncatedClient(), role="er", model="test", system="test", payload={}, audit=audit, validate=json.loads)
        self.assertEqual(audit[0]["failure_category"], "output_truncated")
        self.assertEqual(audit[0]["usage"]["completion_tokens"], 768)
        self.assertEqual(audit[0]["response_metadata"]["finish_reason"], "length")
        self.assertIsNone(response_metadata.get())
        self.assertIsNone(response_usage.get())

    def test_same_catalog_without_patient_labels_or_hidden_results(self):
        cases = json.loads(Path("app/data/voi_synthetic/cases.json").read_text(encoding="utf-8"))
        client = CompactClient()
        read = lambda name: json.loads(Path("app/data/research_synthetic_v1", name + ".json").read_text(encoding="utf-8"))
        report = run_longitudinal(cases, client=client, diagnosis_catalog=["Synthetic A", "Synthetic B"],
                                  registry_manifest=read("registry_local"), routing_utility=read("routing_utility_bounded"), routing_mode="adaptive")
        self.assertEqual(report["status"], "completed")
        self.assertEqual(len(client.payloads), 4)
        self.assertTrue(client.saw_consult_schema)
        for payload in client.payloads:
            self.assertEqual(payload["diagnosis_catalog"], ["Synthetic A", "Synthetic B"])
            self.assertNotIn("hidden_test_results", json.dumps(payload))
        states = [next(iter(v["final_state"]["cases"].values())) for v in report["visits"]]
        self.assertEqual([s["assessment_summary"] for s in states], ["Synthetic A", "Synthetic B"])


if __name__ == "__main__":
    unittest.main()
