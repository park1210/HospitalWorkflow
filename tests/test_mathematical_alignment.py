"""Pure categorical A/B algorithm checks: no medical data and no live model calls."""
from copy import deepcopy
import math
import unittest

from app.core.diagnostic_belief import DiagnosisBelief, posterior, entropy, terminal_choice, validation_utility
from app.core.information_value import action_values, select_action
from app.core.information_outcomes import InformationOutcomes
from app.core.longitudinal_runner import run_longitudinal
from app.core.agent_registry import AgentRegistry
from test_encounter_pipeline import inputs, ScriptedSpecialist


def toy():
    def test(name, sensitivity, cost):
        return {"id": name, "type": "request_test", "target": name,
                "cost": {"money": cost, "minutes": 0, "tokens": 0},
                "outcomes": [
                    {"id": "positive", "likelihood": {"A": sensitivity, "B": 1-sensitivity},
                     "observation": {"source": "objective_findings", "text": name + ": positive"},
                     "supports_diagnoses": ["A"]},
                    {"id": "negative", "likelihood": {"A": 1-sensitivity, "B": sensitivity},
                     "observation": {"source": "objective_findings", "text": name + ": negative"},
                     "supports_diagnoses": ["B"]}]}
    return {"schema_version": 1, "model_id": "categorical-algorithm-validation", "revision": "1",
            "provenance": {"synthetic": True, "review_status": "unreviewed",
                           "assumptions": ["Categorical math toy; not medical evidence"],
                           "utility_scope": "algorithm_validation_only"},
            "diagnoses": {"A": "general_medicine", "B": "general_medicine"},
            "prior": {"A": .5, "B": .5}, "terminal_utility": validation_utility(["A", "B"]),
            "cost_weights": {"money": 1, "minutes": 0, "tokens": 0},
            "actions": [test("Test 1", .9, .1), test("Test 2", .5, .1)]}


def candidates(model):
    return [{"action_id": a["id"], "type": "Test", "action": "request_test", "target": a["target"],
             "cost": a["cost"], "outcome_model": a["id"]} for a in model["actions"]] + [
                 {"action_id": "diagnose", "type": "Diagnose", "action": "diagnose",
                  "target": None, "cost": 0, "outcome_model": None}]


class MathematicalAlignmentTests(unittest.TestCase):
    def test_explicit_belief_and_no_invented_prior(self):
        self.assertEqual(DiagnosisBelief().snapshot(),
                         {"probabilities": None, "status": "unavailable", "reason": "missing_outcome_model"})
        self.assertEqual(DiagnosisBelief({"A": .5, "B": .5}).status, "available")
        with self.assertRaises(ValueError):
            DiagnosisBelief({"A": .5, "B": .6})

    def test_bayes_and_normalization(self):
        b, mass = posterior({"A": .5, "B": .5}, {"A": .9, "B": .1})
        self.assertAlmostEqual(mass, .5)
        self.assertAlmostEqual(b["A"], .9)
        self.assertAlmostEqual(sum(b.values()), 1)
        with self.assertRaises(ValueError):
            posterior(b, {"A": 0, "B": 0})

    def test_entropy_and_ig(self):
        model = toy()
        rows = {r["action_id"]: r for r in action_values(model["prior"], model["actions"], model)}
        self.assertAlmostEqual(entropy(model["prior"]), math.log(2))
        self.assertAlmostEqual(rows["Test 1"]["information_gain_nats"], .3680642071684971)
        self.assertAlmostEqual(rows["Test 2"]["information_gain_nats"], 0)

    def test_q_diagnose_expected_q_and_voi(self):
        m = toy()
        self.assertEqual(
            terminal_choice(m["prior"], m["terminal_utility"]),
            ("A", 0.5),
        )

        scores = action_values(
            m["prior"], m["actions"], m
        )
        by_id = {row["action_id"]: row for row in scores}

        first = by_id["Test 1"]
        self.assertAlmostEqual(
            first["expected_continuation_utility"], 0.9
        )
        self.assertAlmostEqual(first["q_value"], 0.9)
        self.assertAlmostEqual(first["voi"], 0.4)
        self.assertAlmostEqual(first["cost_penalty"], 0.0)

        selected = select_action(
            candidates(m),
            selector="bayesian_voi",
            belief=m["prior"],
            artifact=m,
        )
        self.assertEqual(
            selected["selected_action"]["action_id"], "Test 1"
    )


    def test_cost_monotonicity_and_ig_independence(self):
        """Legacy cost changes must not affect a cost-free policy."""
        m = toy()
        before = action_values(
            m["prior"], [m["actions"][0]], m
        )[0]

        m["actions"][0]["cost"]["money"] += 0.2
        m["actions"][0]["cost"]["minutes"] = 999
        m["actions"][0]["cost"]["tokens"] = 999

        after = action_values(
            m["prior"], [m["actions"][0]], m
        )[0]

        self.assertAlmostEqual(
            before["voi"], after["voi"]
        )
        self.assertAlmostEqual(
            before["q_value"], after["q_value"]
        )
        self.assertAlmostEqual(
            before["information_gain_nats"],
            after["information_gain_nats"],
        )


    def test_confidence_and_cost_choose_diagnose_without_threshold(self):
        """Diagnose when no additional action improves expected value."""
        m = toy()

        for belief in (
            {"A": 0.99, "B": 0.01},
            {"A": 1.0, "B": 0.0},
        ):
            result = select_action(
                candidates(m),
                selector="bayesian_voi",
                belief=belief,
                artifact=m,
            )
            self.assertEqual(
                result["selected_action"]["type"],
                "Diagnose",
            )

        # A cost change must not force an earlier diagnosis.
        m["actions"][0]["cost"]["money"] = 0.8

        result = select_action(
            candidates(m),
            selector="bayesian_voi",
            belief=m["prior"],
            artifact=m,
        )
        self.assertEqual(
            result["selected_action"]["action_id"],
            "Test 1",
        )


    def test_ig_and_voi_are_different_selectors(self):
        """IG and VoI are mathematically distinct criteria."""
        m = toy()
        m["actions"][0]["cost"]["money"] = 2

        args = {
            "belief": m["prior"],
            "artifact": m,
        }

        voi_result = select_action(
            candidates(m),
            selector="bayesian_voi",
            **args,
        )
        ig_result = select_action(
            candidates(m),
            selector="information_gain",
            **args,
        )

    # In this particular symmetric example, both choose Test 1.
    # This does not imply that IG and VoI are identical.
        self.assertEqual(
            voi_result["selected_action"]["action_id"],
            "Test 1",
        )
        self.assertEqual(
            ig_result["selected_action"]["action_id"],
            "Test 1",
        )

        scores = {
            row["action_id"]: row
            for row in action_values(
                m["prior"], m["actions"], m
            )
        }

        self.assertAlmostEqual(
            scores["Test 1"]["voi"], 0.4
        )
        self.assertAlmostEqual(
            scores["Test 2"]["voi"], 0.0
        )
        self.assertGreater(
            scores["Test 1"]["information_gain_nats"],
            scores["Test 2"]["information_gain_nats"],
        )

    def test_missing_and_partial_models_unavailable(self):
        m = toy()
        r = select_action(candidates(m), selector="bayesian_voi")
        self.assertEqual((r["status"], r["reason"]), ("unavailable", "missing_outcome_model"))
        self.assertNotIn("values", r)
        cs = candidates(m)
        cs[0]["outcome_model"] = None
        self.assertEqual(select_action(cs, selector="bayesian_voi", belief=m["prior"], artifact=m)["reason"],
                         "missing_action_outcome_model")

    def test_default_utility_is_marked_validation_only(self):
        m = toy()
        del m["terminal_utility"]
        validated = InformationOutcomes(m).artifact
        self.assertEqual(validated["terminal_utility"]["A"], {"A": 1.0, "B": 0.0})
        self.assertEqual(validated["provenance"]["utility_scope"], "algorithm_validation_only")

    def test_unavailable_model_pipeline_still_terminates_explicitly(self):
        cases, registry = inputs()
        r = run_longitudinal(cases[:1], registry_manifest=registry, routing_mode="adaptive",
                             client=ScriptedSpecialist(), action_selector="bayesian_voi", minute_limit=60)
        self.assertEqual(r["status"], "completed")
        rt = next(iter(r["visits"][0]["final_state"]["cases"].values()))
        for call in rt["llm_audit"]:
            self.assertEqual(call["selector_status"]["status"], "unavailable")
            self.assertEqual(call["selector_status"]["reason"], "missing_outcome_model")
            self.assertEqual(call["selector_status"]["executed_selector"], "specialist_heuristic")
        self.assertIsNone(rt["voi_state"]["diagnosis_belief"]["probabilities"])

    def test_common_router_and_unimplemented_llm_explicit(self):
        _, registry = inputs()
        router = AgentRegistry(registry)
        for name in ("llm", "memory_aware_llm"):
            self.assertEqual(router.select_specialty({}, {}, ["neurology"], router=name)["status"], "unavailable")
        r = router.select_specialty({"chief_complaint": "breathing respiratory"}, {}, ["neurology", "pulmonology"])
        self.assertEqual(r["selected_specialty"], "pulmonology")
        self.assertEqual(r["router"], "RuleSimilarityRouter")

    def test_random_and_heuristic_common_interface(self):
        cs = candidates(toy())
        a = select_action(cs, selector="random", seed=2)
        self.assertEqual(a, select_action(cs, selector="random", seed=2))
        self.assertIn(a["selected_action"], cs)
        self.assertEqual(select_action(cs, selector="specialist_heuristic",
                                       specialist_proposal=cs[0])["selected_action"], cs[0])


if __name__ == "__main__":
    unittest.main()
