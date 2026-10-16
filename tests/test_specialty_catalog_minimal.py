import json
from pathlib import Path
import unittest
from app.core.agent_registry import AgentRegistry
from app.core.routing_collection import collect_outcomes


class FixedClient:
    def __init__(self):
        self.payloads = []

    def chat_json(self, system, prompt, model=None, schema=None):
        payload = json.loads(prompt)
        self.payloads.append(payload)
        assert schema["properties"]["diagnosis"]["enum"] == ["Synthetic A", "Synthetic B"]
        return json.dumps({"diagnosis": "Synthetic A", "rationale": "Test response."})


class SpecialtyCatalogTests(unittest.TestCase):
    def test_shared_catalog_does_not_leak_correct_answer_and_checkpoints(self):
        manifest = json.loads(Path("app/data/research_synthetic_v1/registry_local.json").read_text(encoding="utf-8"))
        probe = {"patient_id": "unit-heldout", "decision_id": "probe", "split": "test",
                 "diagnosis_catalog": ["Synthetic A", "Synthetic B"], "expected_diagnoses": ["Synthetic B"],
                 "observation": {"chief_complaint": "Uncertain", "gold_label": "Synthetic B"}}
        client, checkpoints = FixedClient(), []
        rows = collect_outcomes([probe], AgentRegistry(manifest), client, {}, checkpoint_callback=lambda r: checkpoints.append(len(r)))
        self.assertEqual(checkpoints, [1, 2])
        self.assertTrue(all(not r["correct"] for r in rows))
        for payload in client.payloads:
            self.assertNotIn("expected_diagnoses", payload)
            self.assertNotIn("gold_label", payload["observation"])
            self.assertEqual(payload["diagnosis_catalog"], ["Synthetic A", "Synthetic B"])


if __name__ == "__main__":
    unittest.main()
