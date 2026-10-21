
"""Unit tests for accuracy-only routing and cost-free VoI."""

import unittest
from copy import deepcopy

from app.core.routing_utility import (
    RoutingUtility,
    fit_utility,
)
from app.core.voi_planning import plan_voi
from evaluation.research_metrics import (
    ndcg_at_k,
    classification_metrics,
    risk_coverage_curve,
    paired_bootstrap_ci,
)


def registry_manifest():
    return {
        "schema_version": 1,
        "agents": [
            {
                "agent_id": "er",
                "role": "er",
                "department": "",
                "model": "er-model",
                "version": "v1",
                "keywords": [],
            },
            {
                "agent_id": "neuro",
                "role": "specialty",
                "department": "neurology",
                "model": "neuro-model",
                "version": "v1",
                "keywords": ["headache"],
            },
            {
                "agent_id": "cardio",
                "role": "specialty",
                "department": "cardiology",
                "model": "cardio-model",
                "version": "v1",
                "keywords": ["chest pain"],
            },
        ],
    }


class ResearchMathV2Tests(unittest.TestCase):

    def test_routing_accuracy_only(self):
        from app.core.agent_registry import AgentRegistry

        registry = AgentRegistry(registry_manifest())
        rows = []

        for i in range(3):
            for agent in ("neuro", "cardio"):
                rows.append({
                    "split": "train",
                    "patient_id": "train-p",
                    "decision_id": str(i),
                    "agent_id": agent,
                    "observation": {
                        "chief_complaint": "headache",
                    },
                    "correct": agent == "neuro",
                })

        artifact = fit_utility(rows, registry)
        trained = AgentRegistry(
            registry_manifest(), artifact
        )

        result = trained.route(
            {"chief_complaint": "headache"},
            ["neurology", "cardiology"],
            mode="adaptive",
        )

        self.assertEqual(
            result["selected_specialty"], "neurology"
        )

        self.assertEqual(
            result["decision_status"], "selected"
        )

        self.assertEqual(
            artifact["method"],
            "jaccard_beta_accuracy_v2",
        )

        self.assertNotIn("cost", artifact["samples"][0])
        self.assertNotIn(
            "latency_seconds", artifact["samples"][0]
        )

    def test_legacy_costs_do_not_affect_scores(self):
        from app.core.agent_registry import AgentRegistry

        registry = AgentRegistry(registry_manifest())
        rows = []

        for i in range(2):
            for agent in ("neuro", "cardio"):
                rows.append({
                    "split": "train",
                    "patient_id": "train-p",
                    "decision_id": str(i),
                    "agent_id": agent,
                    "observation": {
                        "chief_complaint": "headache",
                    },
                    "correct": agent == "neuro",
                })

        artifact = fit_utility(rows, registry)

        legacy = deepcopy(artifact)
        legacy["schema_version"] = 1
        legacy["method"] = "jaccard_beta_v1"
        legacy["weights"] = {
            "accuracy": 1,
            "cost": 999999,
            "latency": 999999,
        }

        for sample in legacy["samples"]:
            sample["cost"] = 999999
            sample["latency_seconds"] = 999999

        old_registry = AgentRegistry(
            registry_manifest(), legacy
        )
        new_registry = AgentRegistry(
            registry_manifest(), artifact
        )

        observation = {
            "chief_complaint": "headache"
        }

        old_result = old_registry.route(
            observation,
            ["neurology", "cardiology"],
            mode="adaptive",
        )
        new_result = new_registry.route(
            observation,
            ["neurology", "cardiology"],
            mode="adaptive",
        )

        self.assertEqual(
            old_result["specialty_scores"],
            new_result["specialty_scores"],
        )

    def test_cost_free_multistep_voi(self):
        belief = {"A": 0.5, "B": 0.5}

        utility = {
            "A": {"A": 1.0, "B": 0.0},
            "B": {"A": 0.0, "B": 1.0},
        }

        actions = [
            {
                "id": "test-1",
                "outcomes": [
                    {
                        "id": "positive",
                        "likelihood": {
                            "A": 0.9,
                            "B": 0.1,
                        },
                    },
                    {
                        "id": "negative",
                        "likelihood": {
                            "A": 0.1,
                            "B": 0.9,
                        },
                    },
                ],
            }
        ]

        result = plan_voi(
            belief,
            actions,
            utility,
            horizon=1,
        )

        self.assertAlmostEqual(
            result["baseline_terminal_utility"],
            0.5,
        )

        self.assertAlmostEqual(
            result["optimal_value"],
            0.9,
        )

        self.assertAlmostEqual(
            result["action_values"][0]["voi"],
            0.4,
        )

        self.assertEqual(
            result["selected_action_id"],
            "test-1",
        )

        deeper = plan_voi(
            belief,
            actions,
            utility,
            horizon=3,
        )

        self.assertGreaterEqual(
            deeper["optimal_value"],
            result["optimal_value"],
        )

    def test_ndcg(self):
        score = ndcg_at_k(
            ["relevant", "irrelevant"],
            {"relevant": 2, "irrelevant": 0},
            2,
        )

        self.assertAlmostEqual(score, 1.0)

    def test_macro_f1_and_abstention(self):
        result = classification_metrics(
            ["neurology", "cardiology"],
            [None, "cardiology"],
        )

        self.assertEqual(result["coverage"], 0.5)
        self.assertEqual(result["accuracy"], 0.5)
        self.assertEqual(result["macro_f1"], 0.5)

    def test_risk_coverage(self):
        result = risk_coverage_curve(
            [0.9, 0.4],
            [True, False],
        )

        self.assertEqual(
            result["points"][-1]["risk"],
            0.5,
        )
        self.assertGreaterEqual(result["aurc"], 0)

    def test_bootstrap(self):
        result = paired_bootstrap_ci(
            ["p1", "p2", "p3"],
            [0, 0, 1],
            [1, 1, 1],
            repetitions=200,
            seed=42,
        )

        self.assertAlmostEqual(
            result["difference"],
            2 / 3,
        )
        self.assertLessEqual(
            result["lower"],
            result["upper"],
        )


if __name__ == "__main__":
    unittest.main()
