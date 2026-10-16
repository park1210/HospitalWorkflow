import copy
import json
import tempfile
import unittest
from pathlib import Path

from app.core.hospital_case_runtime import HospitalCaseRuntime
from app.core.hospital_scheduler_state import HospitalSchedulerState
from app.core.hospital_evaluation import evaluation_report, paired_comparison, validate_evaluation, distribution
from app.scripts.evaluate_parallel_run import evaluate_saved_run


def fixture():
    state = HospitalSchedulerState(run_id="evaluation_test", current_minute=21)
    for cid, end, first in (("A", 10, 2), ("B", 20, 4)):
        data = {"case_id": cid, "gold_label": {"diagnosis": "Synthetic diagnosis", "department": "cardiology"},
                "evaluation": {"critical_patient": cid == "A", "deterioration_at_risk": cid == "A",
                    "diagnosis_aliases": ["SYN"], "workflow": {"required_tests": ["CBC"], "considered_tests": [],
                    "acceptable_consultations": ["cardiology"], "critical_actions": []}},
                "temporal_profile": {"flow_deterioration": {"clock": "since_arrival",
                    "worsening_after_min": 1, "critical_after_min": 8}}}
        runtime = HospitalCaseRuntime(cid, data, 0, 0, workflow_state="completed", is_completed=True,
            first_evaluation_min=first, final_diagnosis_min=end, assessment_summary="SYN" if cid == "A" else "wrong",
            target_department="cardiology", completed_tests=["CBC"])
        state.cases[cid] = runtime
    a = state.case("A")
    a.first_deterioration_min = 1
    a.completed_tests = ["blood count", "MRI", "Extra"]
    a.case_data["evaluation"]["workflow"].update(required_tests=["CBC", "CT"], considered_tests=["MRI"],
        test_aliases={"blood count": "CBC"}, critical_actions=[
            {"id": "cbc", "event_type": "result_received", "target": "CBC", "deadline_min": 5},
            {"id": "urgent_consult", "event_type": "consult_started", "target": "neurology", "deadline_min": 3}])

    def event(cid, minute, kind, action="", **payload):
        state.event_log.append({"case_id": cid, "minute": minute, "event_type": kind, "action": action, "payload": payload})
    event("A", 0, "arrival_entered")
    event("A", 2, "question_asked", "ask_history")
    event("A", 3, "test_ordered", "order_test")
    for name in ("blood count", "MRI", "Extra", "Extra"):
        event("A", 4, "result_received", "test_result_ready", requested_test=name)
    event("A", 5, "assessment_completed", "review_results")
    event("A", 6, "consult_requested", "request_specialty")
    event("A", 7, "consult_started", "specialty_consult", department="cardiology")
    event("A", 8, "consult_started", "specialty_consult", department="neurology")
    event("A", 10, "case_completed", "er_finalize")
    event("B", 0, "arrival_entered")
    event("B", 5, "result_received", "test_result_ready", requested_test="CBC")
    event("B", 20, "case_completed", "er_finalize")
    return state


class EvaluationTests(unittest.TestCase):
    def test_exact_all_eleven_metrics(self):
        report = evaluation_report(fixture())
        flat = {name: row for group in report["groups"].values() for name, row in group.items()}
        expected = {"diagnosis_accuracy": 0.5, "department_accuracy": 1, "ntcr": 2/3, "uti": 2/3,
                    "ucr": 0.5, "camr": 0.5, "apl": 3, "ttd": 15, "mwt": 3, "cpwt": 2, "dber": 1}
        self.assertEqual(len(flat), 11)
        for name, value in expected.items():
            with self.subTest(metric=name):
                self.assertAlmostEqual(flat[name]["value"], value)
        self.assertEqual(flat["ttd"]["observed_distribution"]["iqr"], 5)
        self.assertEqual(report["cases"][0]["missed_critical_action_ids"], ["urgent_consult"])
        self.assertFalse(report["validity"]["independent_clinical_evaluation"])

    def test_missing_workflow_is_not_zero_or_inferred(self):
        state = fixture()
        state.case("A").case_data["evaluation"].pop("workflow")
        report = evaluation_report(state)
        for name in ("ntcr", "uti", "ucr"):
            self.assertIsNone(report["groups"]["process"][name]["value"])
        self.assertIsNone(report["groups"]["safety"]["camr"]["value"])
        self.assertEqual(report["groups"]["process"]["ntcr"]["observed_value"], 1)

    def test_incomplete_case_is_censored_not_scored_wrong(self):
        state = fixture()
        state.case("B").is_completed = False
        state.case("B").final_diagnosis_min = None
        report = evaluation_report(state)
        self.assertIsNone(report["groups"]["outcome"]["diagnosis_accuracy"]["value"])
        self.assertEqual(report["groups"]["outcome"]["diagnosis_accuracy"]["observed_value"], 1)
        self.assertIsNone(report["groups"]["efficiency"]["ttd"]["value"])
        self.assertEqual(report["groups"]["multi_patient"]["mwt"]["value"], 3)

    def test_zero_consults_and_zero_required_are_na(self):
        state = fixture()
        state.cases = {"B": state.case("B")}
        state.case("B").case_data["evaluation"]["workflow"]["required_tests"] = []
        report = evaluation_report(state)
        for name in ("ntcr", "uti", "ucr"):
            self.assertIsNone(report["groups"]["process"][name]["value"])
            self.assertEqual(report["groups"]["process"][name]["status"], "not_applicable")

    def test_dber_boundary_and_missing_at_risk_labels(self):
        state = fixture()
        state.case("A").first_deterioration_min = 2
        self.assertEqual(evaluation_report(state)["groups"]["multi_patient"]["dber"]["value"], 0)
        state.case("B").case_data["evaluation"].pop("deterioration_at_risk")
        self.assertIsNone(evaluation_report(state)["groups"]["multi_patient"]["dber"]["value"])

    def test_truncated_trace_does_not_pretend_no_actions_missed(self):
        state = fixture()
        state.event_log = [e for e in state.event_log if e["event_type"] != "arrival_entered"]
        report = evaluation_report(state)
        self.assertIsNone(report["groups"]["safety"]["camr"]["value"])
        self.assertIsNone(report["groups"]["efficiency"]["apl"]["value"])

    def test_evaluator_does_not_mutate_state(self):
        state = fixture()
        before = copy.deepcopy(state)
        evaluation_report(state)
        self.assertEqual(state, before)

    def test_paired_same_cases_and_reject_mismatch(self):
        left = evaluation_report(fixture())
        state = fixture()
        state.case("A").first_evaluation_min += 2
        right = evaluation_report(state)
        result = paired_comparison(left, right)
        self.assertEqual(result["metrics"]["mwt"]["delta_distribution"]["mean"], 1)
        right["cases"][0]["case_signature"] = "different"
        with self.assertRaises(ValueError):
            paired_comparison(left, right)

    def test_invalid_annotations(self):
        for annotation in ({"critical_patient": "true"},
                           {"workflow": {"required_tests": "CBC"}},
                           {"workflow": {"critical_actions": [{"id": "x", "event_type": "invented"}]}},
                           {"workflow": {"test_aliases": {"a": "b", "b": "a"}}}):
            with self.subTest(annotation=annotation), self.assertRaises(ValueError):
                validate_evaluation({"evaluation": annotation})

    def test_saved_run_offline_evaluation(self):
        state = fixture()
        saved = {"source_cases": [c.case_data for c in state.cases.values()], "final_state": state.snapshot()}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "run.json"
            path.write_text(json.dumps(saved), encoding="utf-8")
            result = evaluate_saved_run(path)
            self.assertEqual(result["groups"]["process"]["uti"]["value"], 2/3)
            sidecar = Path(folder) / "annotations.json"
            sidecar.write_text(json.dumps({"unknown": {}}), encoding="utf-8")
            with self.assertRaises(ValueError):
                evaluate_saved_run(path, sidecar)

    def test_distribution_small_samples(self):
        self.assertIsNone(distribution([])["mean"])
        self.assertEqual(distribution([5])["iqr"], 0)
        self.assertEqual(distribution([0, 10])["median"], 5)

    def test_scheduler_report_integration(self):
        from test_hospital_flow import cases
        from app.core.hospital_parallel_runner import run_parallel_scheduler_preview
        inputs = cases(1)
        inputs[0]["evaluation"] = {"workflow": {"required_tests": ["Blood Test"],
            "considered_tests": [], "acceptable_consultations": [], "critical_actions": []}}
        report = run_parallel_scheduler_preview(inputs, minute_limit=100)["evaluation_metrics"]
        self.assertEqual(report["groups"]["process"]["ntcr"]["value"], 1)
        self.assertEqual(report["groups"]["process"]["uti"]["value"], 0)
        self.assertGreater(report["groups"]["efficiency"]["apl"]["value"], 0)


if __name__ == "__main__":
    unittest.main()
