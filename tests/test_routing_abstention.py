
"""Tests for explicit routing decision status and abstention."""

import unittest

from app.core.agent_registry import AgentRegistry
from app.core.routing_utility import fit_utility
from app.core.routing_evaluation import (
    decisions_from_outcomes,
    evaluate_routing,
)


def manifest():
    return {
        "schema_version": 1,
        "agents": [
            {
                "agent_id": "er",
                "role": "er",
                "department": "",
                "model": "test-er",
                "version": "v1",
                "keywords": [],
            },
            {
                "agent_id": "neuro",
                "role": "specialty",
                "department": "neurology",
                "model": "test-neuro",
                "version": "v1",
                "keywords": ["headache"],
            },
            {
                "agent_id": "cardio",
                "role": "specialty",
                "department": "cardiology",
                "model": "test-cardio",
                "version": "v1",
                "keywords": ["chest pain"],
            },
        ],
    }


def training():
    rows = []

    for index in range(2):
        for agent_id in ("neuro", "cardio"):
            rows.append({
                "split": "train",
                "patient_id": "training-patient",
                "decision_id": str(index),
                "agent_id": agent_id,
                "observation": {
                    "chief_complaint": "headache"
                },
                "correct": agent_id == "neuro",
                "cost": 0.1,
                "latency_seconds": 1,
            })

    return rows


class RoutingAbstentionTests(unittest.TestCase):
    def setUp(self):
        base = AgentRegistry(manifest())

        artifact = fit_utility(
            training(),
            base,
        )

        self.registry = AgentRegistry(
            manifest(),
            artifact,
        )

    def test_single_candidate_abstains_without_support(self):
        result = self.registry.route(
            {"chief_complaint": "unseen"},
            ["neurology"],
            mode="adaptive",
        )

        self.assertEqual(
            result["allowed_departments"],
            ["neurology"],
        )
        self.assertIsNone(
            result["selected_specialty"]
        )
        self.assertEqual(
            result["decision_status"],
            "abstained",
        )

    def test_multiple_candidates_abstain(self):
        result = self.registry.route(
            {"chief_complaint": "unseen"},
            ["neurology", "cardiology"],
            mode="adaptive",
        )

        self.assertEqual(
            result["allowed_departments"],
            ["cardiology", "neurology"],
        )
        self.assertIsNone(
            result["selected_specialty"]
        )
        self.assertEqual(
            result["decision_status"],
            "abstained",
        )

    def test_supported_case_is_selected(self):
        result = self.registry.route(
            {"chief_complaint": "headache"},
            ["neurology", "cardiology"],
            mode="adaptive",
        )

        self.assertEqual(
            result["decision_status"],
            "selected",
        )
        self.assertEqual(
            result["selected_specialty"],
            "neurology",
        )

    def test_llm_mode_is_delegated(self):
        result = self.registry.route(
            {"chief_complaint": "headache"},
            ["neurology"],
            mode="llm",
        )

        self.assertEqual(
            result["decision_status"],
            "delegated",
        )
        self.assertIsNone(
            result["selected_specialty"]
        )
        self.assertEqual(
            result["allowed_departments"],
            ["neurology"],
        )

    def test_no_candidates_is_unavailable(self):
        result = self.registry.route(
            {"chief_complaint": "headache"},
            [],
            mode="adaptive",
        )

        self.assertEqual(
            result["decision_status"],
            "unavailable",
        )
        self.assertIsNone(
            result["selected_specialty"]
        )

    def test_single_candidate_abstention_has_no_regret(self):
        held_out = [
            {
                **row,
                "split": "test",
                "patient_id": "held-out-patient",
                "observation": {
                    "chief_complaint": "unseen"
                },
            }
            for row in training()[:2]
        ]

        decisions = decisions_from_outcomes(
            held_out,
            self.registry,
        )

        result = evaluate_routing(
            decisions,
            self.registry.utility,
        )

        self.assertEqual(
            result["coverage"],
            0.0,
        )
        self.assertIsNone(
            result["mean_regret"]
        )
        self.assertEqual(
            result["abstention_count"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
