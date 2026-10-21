"""Small offline checks only; broader experiments are documented for manual use."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from app.core.diagnostic_belief import posterior, entropy
from app.core.information_outcomes import InformationOutcomes
from app.core.information_value import action_values
from app.core.longitudinal_runner import run_longitudinal
from app.core.voi_evaluation import evaluate_voi, fit_outcomes


def read(name):
    return json.loads(Path("app/data/voi_synthetic/" + name + ".json").read_text(encoding="utf-8"))


class NoModelCalls:
    def chat(self, *args, **kwargs):
        raise AssertionError("This synthetic decisive path must not call an LLM")


class VoIMinimalTests(unittest.TestCase):
    def test_bayes_information_value_and_horizon(self):
        model = read("model")
        InformationOutcomes(model)
        belief, mass = posterior(model["prior"], model["actions"][0]["outcomes"][0]["likelihood"])
        self.assertAlmostEqual(mass, .5)
        self.assertAlmostEqual(belief["Synthetic A"], .99)
        self.assertLess(entropy(belief), entropy(model["prior"]))
        scores = action_values(model["prior"], model["actions"], model)
        self.assertEqual(scores[0]["action_id"], "test-t")
        self.assertAlmostEqual(scores[0]["voi"], .49)
        model["horizon"] = 2
        self.assertGreaterEqual(action_values(model["prior"], model["actions"], model)[0]["voi"], .44 - 1e-9)

    def test_schema_unknown_and_future_results(self):
        model = read("model")
        engine = InformationOutcomes(model)
        belief, matched = engine.observe({"hidden_test_results": {"T": {"result": "Synthetic A finding"}}})
        self.assertEqual(belief, model["prior"])
        self.assertEqual(matched, [])
        with self.assertRaises(ValueError):
            engine.observe({"objective_findings": ["T: outside model"]})
        broken = deepcopy(model)
        broken["actions"][0]["outcomes"][0]["likelihood"]["Synthetic A"] = .5
        with self.assertRaises(ValueError):
            InformationOutcomes(broken)

    def test_engine_decisive_path_without_calls_and_deferred_memory(self):
        report = run_longitudinal(read("cases"), voi_model=read("model"), client=NoModelCalls(),
                                  mode="full_history", memory_source="fixed", initial_memory=read("memory")["records"])
        self.assertEqual(report["status"], "completed")
        score = evaluate_voi(report, read("labels"))
        self.assertEqual(score["accuracy"], 1)
        for visit in report["visits"]:
            state = next(iter(visit["final_state"]["cases"].values()))
            self.assertEqual(state["llm_audit"], [])
            self.assertEqual(state["memory_context"]["mode"], "none")
            self.assertEqual(state["voi_state"]["history"][0]["action_id"], "test-t")
            self.assertEqual(state["voi_state"]["history"][-1]["selected_action"], "diagnose")

    def test_fitting_and_patient_leakage_guard(self):
        fitted = fit_outcomes(read("model"), read("training_outcomes"))
        InformationOutcomes(fitted)
        cases = read("cases")
        cases[0]["longitudinal"]["patient_id"] = "voi-train-0"
        with self.assertRaisesRegex(ValueError, "overlap"):
            run_longitudinal(cases, voi_model=fitted, client=NoModelCalls())


if __name__ == "__main__":
    unittest.main()
