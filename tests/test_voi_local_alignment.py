"""Focused regression tests for uploaded InformationPolicy code."""
import unittest

from app.core.information_value import action_values, select_action


def model():
    def test(name, sensitivity, cost):
        return {
            "id": name, "type": "request_test", "target": name,
            "cost": {"money": cost, "minutes": 0, "tokens": 0},
            "outcomes": [
                {"id": "positive", "likelihood": {"A": sensitivity, "B": 1 - sensitivity}},
                {"id": "negative", "likelihood": {"A": 1 - sensitivity, "B": sensitivity}},
            ],
        }
    return {
        "prior": {"A": 0.5, "B": 0.5},
        "terminal_utility": {
            "A": {"A": 1, "B": 0},
            "B": {"A": 0, "B": 1},
        },
        "horizon": 2,
        "actions": [test("strong", 0.9, 0.1), test("weak", 0.6, 5.0)],
    }


def candidates(data):
    return [
        {"action_id": a["id"], "type": "Test", "action": "request_test",
         "target": a["target"], "outcome_model": a["id"]}
        for a in data["actions"]
    ] + [{"action_id": "diagnose", "type": "Diagnose", "action": "diagnose",
          "target": None, "outcome_model": None}]


class VoILocalAlignmentTests(unittest.TestCase):
    def test_one_step_ignores_legacy_cost(self):
        data = model()
        before = action_values(data["prior"], data["actions"], data)
        data["actions"][0]["cost"]["money"] = 100000
        after = action_values(data["prior"], data["actions"], data)
        self.assertEqual(before, after)
        self.assertAlmostEqual(before[0]["voi"], 0.4)

    def test_horizon_is_forwarded_in_real_selector(self):
        data = model()
        data["horizon"] = 1
        first = select_action(candidates(data), selector="bayesian_voi",
                              belief=data["prior"], artifact=data)
        data["horizon"] = 2
        second = select_action(candidates(data), selector="bayesian_voi",
                               belief=data["prior"], artifact=data)
        self.assertEqual(first["horizon"], 1)
        self.assertEqual(second["horizon"], 2)
        self.assertEqual(first["cost_model"], "none")
        self.assertEqual(second["cost_model"], "none")
        self.assertGreaterEqual(second["values"][0]["q_value"], first["values"][0]["q_value"] - 1e-12)

    def test_unsupported_action_never_uses_unmodeled_probability(self):
        data = model()
        cs = candidates(data)
        cs[0]["outcome_model"] = None
        result = select_action(cs, selector="bayesian_voi", belief=data["prior"], artifact=data)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "missing_action_outcome_model")


if __name__ == "__main__":
    unittest.main()
