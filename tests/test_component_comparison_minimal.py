from copy import deepcopy
import json
from pathlib import Path
import unittest

from app.core.embedding_builder import build_embeddings
from app.core.agent_registry import AgentRegistry
from app.scripts.compare_memory_retrieval import compare as memory_compare
from app.scripts.compare_routing_baselines import compare as routing_compare


def read(folder, name):
    return json.loads(Path("app/data", folder, name + ".json").read_text(encoding="utf-8"))


class ComponentComparisonTests(unittest.TestCase):
    def test_vector_provenance_and_query_mismatch(self):
        cases = read("challenge_v1", "cases_validation")
        memory = read("challenge_v1", "memory")
        annotations = read("challenge_v1", "annotations_validation")
        vectors = build_embeddings(memory["records"], cases)
        result = memory_compare(cases, memory, annotations, embeddings=vectors)
        self.assertEqual(result["new_model_calls"], 0)
        self.assertIn("lexical_hash_vectors", {r["method"] for r in result["rows"]})
        self.assertNotIn("saved_model_vectors", {r["method"] for r in result["rows"]})
        altered = deepcopy(cases)
        altered[0]["doctor_visible_info"]["chief_complaint"] = "changed query"
        with self.assertRaisesRegex(ValueError, "query embedding"):
            memory_compare(altered, memory, annotations, embeddings=vectors)

    def test_missing_counterfactuals_and_training_overlap(self):
        registry = AgentRegistry(read("research_synthetic_v1", "registry_local"), read("research_synthetic_v1", "routing_utility_bounded"))
        outcomes = read("research_synthetic_v1", "routing_test_bounded")
        missing = deepcopy(outcomes)
        missing[0]["cost"] = None
        result = routing_compare(missing, registry)
        for row in result["results"]:
            self.assertIsNone(row["evaluation"]["mean_regret"])
            self.assertLess(row["evaluation"]["coverage"], 1)
        overlap = deepcopy(outcomes)
        overlap[0]["patient_id"] = next(iter(registry.utility.training_patients))
        with self.assertRaises(ValueError):
            routing_compare(overlap, registry)


if __name__ == "__main__":
    unittest.main()
