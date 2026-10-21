
"""Unit tests for the independent Routing Benchmark."""

import unittest

from app.core.agent_registry import AgentRegistry

from benchmark.routing.validate_routing_gold import (
    validate_routing_gold,
)
from benchmark.routing.evaluate_routing_benchmark import (
    evaluate_routing_benchmark,
)
from benchmark.routing.run_routing_benchmark import (
    run_routing_benchmark,
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


def cases():
    return [
        {
            "case_id": "pilot_001",
            "patient_id": "patient_001",
            "split": "test",
            "candidate_departments": [
                "neurology",
                "cardiology",
            ],
            "observation": {
                "chief_complaint": "headache",
                "current_symptoms": [],
                "objective_findings": [],
            },
            "gold": {
                "review_status": "reviewed",
                "review_reference": "synthetic_fixture_001",
                "primary_specialty": "neurology",
                "acceptable_specialties": ["neurology"],
            },
        },
        {
            "case_id": "pilot_002",
            "patient_id": "patient_002",
            "split": "test",
            "candidate_departments": [
                "neurology",
                "cardiology",
            ],
            "observation": {
                "chief_complaint": "chest pain",
                "current_symptoms": [],
                "objective_findings": [],
            },
            "gold": {
                "review_status": "reviewed",
                "review_reference": "synthetic_fixture_002",
                "primary_specialty": "cardiology",
                "acceptable_specialties": ["cardiology"],
            },
        },
    ]


class RoutingBenchmarkTests(unittest.TestCase):

    def test_gold_validation(self):
        report = validate_routing_gold(cases())

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["validated_cases"] if
                         "validated_cases" in report
                         else report["case_count"], 2)

    def test_rule_baseline(self):
        registry = AgentRegistry(manifest())

        result = run_routing_benchmark(
            cases(),
            registry,
            modes=("rule",),
        )

        summary = result["summary"][0]

        self.assertEqual(summary["coverage"], 1.0)
        self.assertEqual(
            summary["overall_success_rate"], 1.0
        )
        self.assertEqual(summary["macro_f1"], 1.0)

    def test_abstention_not_counted_as_correct(self):
        predictions = {
            "policy": {
                "pilot_001": {
                    "decision_status": "abstained",
                    "selected_specialty": None,
                },
                "pilot_002": {
                    "decision_status": "selected",
                    "selected_specialty": "cardiology",
                },
            }
        }

        result = evaluate_routing_benchmark(
            cases(),
            predictions,
        )

        summary = result["summary"][0]

        self.assertEqual(summary["coverage"], 0.5)
        self.assertEqual(
            summary["selective_accuracy"], 1.0
        )
        self.assertEqual(
            summary["overall_success_rate"], 0.5
        )
        self.assertEqual(summary["macro_f1"], 0.5)

    def test_unreviewed_gold_rejected(self):
        data = cases()
        data[0]["gold"]["review_status"] = "pending"

        with self.assertRaises(ValueError):
            validate_routing_gold(data)

    def test_gold_not_exposed_to_router(self):
        class SpyRegistry(AgentRegistry):
            def route(
                self,
                observation,
                departments,
                *,
                mode="llm",
                seed=0,
            ):
                self.last_observation = observation

                return super().route(
                    observation,
                    departments,
                    mode=mode,
                    seed=seed,
                )

        data = cases()
        data[0]["observation"]["gold_label"] = "secret"
        data[0]["observation"]["hidden_test_results"] = {
            "secret": True
        }

        registry = SpyRegistry(manifest())

        run_routing_benchmark(
            data,
            registry,
            modes=("rule",),
        )

        self.assertNotIn(
            "gold_label",
            registry.last_observation,
        )
        self.assertNotIn(
            "hidden_test_results",
            registry.last_observation,
        )

    def test_single_candidate_abstention_metric(self):
        data = cases()[:1]
        data[0]["candidate_departments"] = ["neurology"]

        predictions = {
            "adaptive": {
                "pilot_001": {
                    "decision_status": "abstained",
                    "selected_specialty": None,
                },
            },
        }

        result = evaluate_routing_benchmark(
            data,
            predictions,
        )

        summary = result["summary"][0]

        self.assertEqual(summary["coverage"], 0.0)
        self.assertEqual(summary["abstention_rate"], 1.0)
        self.assertIsNone(
            summary["selective_accuracy"]
        )


if __name__ == "__main__":
    unittest.main()
