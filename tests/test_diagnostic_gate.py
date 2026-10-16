import json
import unittest

from app.core.hospital_parallel_scheduler import HospitalParallelScheduler
from app.core.hospital_llm_policy import HospitalLLMPolicy
from app.core.diagnostic_evidence import diagnostic_evidence
from app.llm.role_call import RoleCallError


def response(action="diagnose", certainty="unresolved", indices=None, target="synthetic diagnosis"):
    return json.dumps({"action": action, "target": target, "rationale": "Select the next step using observed information.",
        "assessment": "unresolved complaint", "department": "general_medicine", "certainty": certainty,
        "evidence_indices": indices or []})


class Client:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.payloads = []
        self.schemas = []

    def chat_json(self, system, user, model=None, schema=None):
        self.payloads.append(json.loads(user))
        self.schemas.append(schema)
        return next(self.responses)


def source():
    return {"case_id": "gate", "doctor_visible_info": {"chief_complaint": "synthetic complaint",
        "initial_vitals": {"spo2": 98}}, "patient_visible_info": {"history": "Started today."},
        "available_tests": ["T"], "hidden_test_results": {"T": {"result": "synthetic objective finding"}}}


class DiagnosticGateTests(unittest.TestCase):
    def runtime(self):
        return HospitalParallelScheduler().initialize([source()]).case("gate")

    def policy(self, client, max_decisions=12, max_questions=2):
        policy = HospitalLLMPolicy({"max_decisions": max_decisions, "max_questions": max_questions}, client=client)
        policy.departments = ["neurology"]
        return policy

    def test_unknown_is_excluded_but_negative_findings_preserved(self):
        runtime = self.runtime()
        runtime.question_history = [{"answer": "I am not sure about that."},
                                    {"answer": "No fever."}, {"answer": "arbitrary", "answer_status": "unknown"}]
        runtime.objective_findings = ["T: Result unavailable in source data", "T2: No lesion detected", None, "T3: null"]
        runtime.consult_history = [{"opinion": "Consider further testing", "department": "neurology"}]
        rows, excluded = diagnostic_evidence(runtime)
        self.assertEqual([r["text"] for r in rows if r["supports_finalization"]], ["T2: No lesion detected"])
        self.assertIn("No fever.", [r["text"] for r in rows])
        self.assertEqual({r["kind"] for r in rows}, {"objective_finding", "patient_history", "vital_sign", "specialty_opinion"})
        self.assertEqual(len(excluded), 5)

    def test_unknown_answer_and_vital_alone_cannot_finalize_supported(self):
        runtime = self.runtime()
        runtime.question_history = [{"answer": "I am not sure about that."}]
        client = Client(response(certainty="supported", indices=[0]))
        with self.assertRaises(RoleCallError):
            self.policy(client).evaluate_er_case(runtime, doctor_id="er")
        self.assertNotIn("diagnose", client.payloads[0]["allowed_actions"])
        self.assertEqual(client.payloads[0]["supported_diagnosis_eligible_indices"], [])
        self.assertFalse(runtime.is_completed)

    def test_early_unresolved_rejected_even_when_objective_finding_exists(self):
        runtime = self.runtime()
        runtime.objective_findings = ["T: actual released finding"]
        client = Client(response())
        with self.assertRaises(RoleCallError):
            self.policy(client).evaluate_er_case(runtime, doctor_id="er")
        self.assertFalse(client.payloads[0]["allow_unresolved_finalization"])
        branches = client.schemas[0]["anyOf"]
        final = next(b for b in branches if b["properties"]["action"]["enum"] == ["diagnose"])
        self.assertEqual(final["properties"]["certainty"]["enum"], ["supported"])

    def test_decisive_objective_citation_can_finish_early(self):
        runtime = self.runtime()
        runtime.objective_findings = ["T: synthetic objective finding"]
        client = Client(response(certainty="supported", indices=[0]))
        result = self.policy(client).evaluate_er_case(runtime, doctor_id="er")
        self.assertEqual(result["action"], "er_finalize")
        self.assertEqual(len(client.payloads), 1)
        self.assertFalse(runtime.llm_audit[-1]["decision_validation"]["clinical_support_verified"])

    def test_patient_only_citation_rejected_even_with_uncited_objective_finding(self):
        runtime = self.runtime()
        runtime.objective_findings = ["T: finding"]
        runtime.question_history = [{"answer": "Started today."}]
        with self.assertRaises(RoleCallError):
            self.policy(Client(response(certainty="supported", indices=[1]))).evaluate_er_case(runtime, doctor_id="er")

    def test_budget_and_exhaustion_are_distinct_reasons(self):
        runtime = self.runtime()
        self.policy(Client(response()), max_decisions=1).evaluate_er_case(runtime, doctor_id="er")
        self.assertEqual(runtime.llm_audit[-1]["decision_validation"]["termination_reason"], "decision_budget_exhausted")
        runtime = self.runtime()
        runtime.case_data["available_tests"] = []
        runtime.question_history = [{"answer": "I am not sure about that."}]
        policy = self.policy(Client(response()), max_questions=1)
        policy.departments = []
        result = policy.evaluate_er_case(runtime, doctor_id="er")
        self.assertEqual(result["certainty"], "unresolved")
        self.assertEqual(runtime.llm_audit[-1]["decision_validation"]["termination_reason"], "available_steps_exhausted")

    def test_scheduler_unknown_then_test_then_diagnosis(self):
        client = Client(response("ask_patient", target="When did your symptoms start?"),
            '{"fact_ids":[],"unknown":true}', response("request_test", target="T"),
            response(certainty="supported", indices=[0]))
        scheduler = HospitalParallelScheduler({"clinical": {"mode": "llm_required"}}, llm_client=client)
        state = scheduler.initialize([source()])
        scheduler.run_until(state, 60)
        runtime = state.case("gate")
        self.assertTrue(runtime.is_completed)
        self.assertEqual(runtime.question_history[0]["answer_status"], "unknown")
        self.assertNotIn("I am not sure about that.", client.payloads[2]["evidence"])
        self.assertEqual(runtime.completed_tests, ["T"])
        self.assertEqual(len(runtime.llm_audit), 4)


if __name__ == "__main__":
    unittest.main()
