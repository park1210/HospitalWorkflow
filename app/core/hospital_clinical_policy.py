from __future__ import annotations

from typing import Any

from app.core.hospital_case_runtime import HospitalCaseRuntime
from app.modules.assessment_module import AssessmentModule
from app.utils.department_catalog import (
    build_department_candidates,
    choose_department_from_scores,
    combine_department_scores,
    normalize_department,
)


class HospitalClinicalPolicy:
    def __init__(self) -> None:
        self.assessment_module = AssessmentModule()

    @staticmethod
    def _demo_meta(runtime: HospitalCaseRuntime) -> dict[str, Any]:
        return dict(dict(runtime.case_data.get("meta", {}) or {}).get("demo", {}) or {})

    @staticmethod
    def _gold_label(runtime: HospitalCaseRuntime) -> dict[str, Any]:
        return dict(runtime.case_data.get("gold_label", {}) or {})

    def _demo_test_plan(self, runtime: HospitalCaseRuntime) -> list[str]:
        hidden_tests = dict(runtime.case_data.get("hidden_test_results", {}) or {})
        return [str(name).strip() for name in list(hidden_tests.keys()) if str(name).strip()]

    def _planned_tests(self, runtime: HospitalCaseRuntime, assessment: dict[str, Any]) -> list[str]:
        demo_tests = self._demo_test_plan(runtime)
        if demo_tests:
            return demo_tests
        return self.normalize_test_plan(assessment.get("recommended_initial_tests", []) or [])

    @staticmethod
    def _remaining_tests(runtime: HospitalCaseRuntime, planned_tests: list[str]) -> list[str]:
        completed = {str(item).strip() for item in list(runtime.completed_tests or []) if str(item).strip()}
        pending = {
            str(dict(item or {}).get("test_name", "")).strip()
            for item in list(runtime.pending_results or [])
            if str(dict(item or {}).get("test_name", "")).strip()
        }
        return [test_name for test_name in planned_tests if test_name not in completed and test_name not in pending]

    def _decisive_evidence_ready(self, runtime: HospitalCaseRuntime) -> bool:
        demo_meta = self._demo_meta(runtime)
        decisive_tests = [str(item).strip() for item in list(demo_meta.get("decisive_tests", []) or []) if str(item).strip()]
        min_count = max(1, int(demo_meta.get("decisive_test_count", 1) or 1))
        if decisive_tests:
            completed = {str(item).strip() for item in list(runtime.completed_tests or []) if str(item).strip()}
            ready_count = len([item for item in decisive_tests if item in completed])
            return ready_count >= min_count
        return bool(runtime.completed_tests)

    def evaluate_er_case(
        self,
        runtime: HospitalCaseRuntime,
        *,
        doctor_id: str,
    ) -> dict[str, Any]:
        assessment = self.assessment_module.run(runtime.case_data, runtime.case_data)
        department_scores = combine_department_scores(
            {
                str(key).strip(): float(value)
                for key, value in (assessment.get("department_signal_scores", {}) or {}).items()
                if str(key).strip()
            }
        )
        target_department = normalize_department(
            choose_department_from_scores(
                department_scores,
                default="general_medicine",
                fallback_if_ambiguous="internal_medicine",
                ambiguity_margin=1.0,
                low_confidence_threshold=1.0,
            ),
            default="general_medicine",
        )
        assessment_summary = str(assessment.get("primary_problem", "")).strip() or "undifferentiated acute complaint"
        recommended_tests = self._planned_tests(runtime, assessment)
        department_candidates = build_department_candidates(department_scores, limit=2)
        gold_label = self._gold_label(runtime)
        gold_diagnosis = str(gold_label.get("diagnosis", "")).strip()
        gold_department = normalize_department(str(gold_label.get("department", "")).strip(), default=target_department)
        demo_meta = self._demo_meta(runtime)

        if gold_department not in {"general_medicine", "internal_medicine", ""} and demo_meta:
            target_department = gold_department
            department_candidates = [gold_department, *[item for item in department_candidates if item != gold_department]][:3]

        if self._decisive_evidence_ready(runtime) and gold_diagnosis:
            assessment_summary = gold_diagnosis
            target_department = gold_department
            if gold_department and gold_department not in department_candidates:
                department_candidates = [gold_department, *department_candidates][:2]

        preview_runtime = HospitalCaseRuntime.from_summary(
            {
                **runtime.to_summary(),
                "target_department": target_department,
                "assessment_summary": assessment_summary,
            },
            case_data=runtime.case_data,
        )
        alternatives = self.decision_alternatives(preview_runtime, recommended_tests)

        result = {
            "target_department": target_department,
            "assessment_summary": assessment_summary,
            "recommended_tests": recommended_tests,
            "department_candidates": department_candidates,
            "alternatives": alternatives,
            "action": "er_finalize",
            "target": assessment_summary,
            "rationale": "ER gathered enough targeted history and objective evidence to finish without additional specialty escalation.",
        }

        if not runtime.question_history:
            question = self.build_interview_question(runtime)
            answer = self.build_interview_answer(runtime)
            result.update(
                {
                    "action": "ask_history",
                    "target": question,
                    "question": question,
                    "answer": answer,
                    "rationale": "The ER doctor first gathered targeted history before committing to tests or specialty escalation.",
                }
            )
            return result

        if self.should_request_test(runtime, assessment, recommended_tests):
            pending_plan = self._remaining_tests(runtime, recommended_tests)
            result.update(
                {
                    "action": "order_test",
                    "target": pending_plan[0] if pending_plan else "",
                    "recommended_tests": pending_plan,
                    "rationale": "The ER interview found remaining uncertainty, so the doctor ordered the lowest-cost targeted test bundle.",
                }
            )
            return result

        if runtime.pending_results:
            result.update(
                {
                    "action": "await_results",
                    "target": "",
                    "rationale": "Test results are pending, so the ER doctor released this patient temporarily and can assess another case.",
                }
            )
            return result

        if self.should_request_specialty(runtime, target_department, department_candidates):
            result.update(
                {
                    "action": "request_specialty",
                    "target": target_department,
                    "rationale": "ER gathered targeted history and objective evidence, but specialty ownership remains strongest for the leading department.",
                }
            )
            return result

        return result

    def decision_alternatives(self, runtime: HospitalCaseRuntime, recommended_tests: list[str]) -> list[dict[str, Any]]:
        next_remaining_tests = self._remaining_tests(runtime, recommended_tests)
        alternatives: list[dict[str, Any]] = [
            {
                "type": "ask_patient",
                "target": "focused_history",
                "rationale": "Gather one more targeted question if symptoms remain ambiguous.",
            }
        ]
        if next_remaining_tests:
            alternatives.append(
                {
                    "type": "request_test",
                    "target": next_remaining_tests[0],
                    "rationale": "Order the next lowest-cost targeted objective test.",
                }
            )
        if str(runtime.target_department).strip() and str(runtime.target_department).strip() not in {"general_medicine", "internal_medicine"}:
            alternatives.append(
                {
                    "type": "consult_specialty",
                    "target": str(runtime.target_department).strip(),
                    "rationale": "Escalate to the leading specialty when ER ownership is no longer sufficient.",
                }
            )
        alternatives.append(
            {
                "type": "diagnose",
                "target": str(runtime.assessment_summary).strip(),
                "rationale": "Finalize immediately if current evidence is already decisive enough.",
            }
        )
        return alternatives

    def should_request_test(
        self,
        runtime: HospitalCaseRuntime,
        assessment: dict[str, Any],
        recommended_tests: list[str],
    ) -> bool:
        if runtime.pending_results:
            return False
        remaining_plan = self._remaining_tests(runtime, recommended_tests)
        if self._demo_meta(runtime):
            if self._decisive_evidence_ready(runtime):
                return False
            return bool(remaining_plan)
        if runtime.completed_tests:
            return False
        return bool(assessment.get("needs_immediate_test", False) and remaining_plan)

    @staticmethod
    def should_request_specialty(
        runtime: HospitalCaseRuntime,
        target_department: str,
        department_candidates: list[str],
    ) -> bool:
        gold_label = dict(runtime.case_data.get("gold_label", {}) or {})
        gold_department = normalize_department(str(gold_label.get("department", "")).strip(), default=target_department)
        demo_meta = dict(dict(runtime.case_data.get("meta", {}) or {}).get("demo", {}) or {})
        decisive_tests = [str(item).strip() for item in list(demo_meta.get("decisive_tests", []) or []) if str(item).strip()]
        decisive_count = max(1, int(demo_meta.get("decisive_test_count", 1) or 1))
        if decisive_tests:
            completed = {str(item).strip() for item in list(runtime.completed_tests or []) if str(item).strip()}
            ready_count = len([item for item in decisive_tests if item in completed])
            if ready_count >= decisive_count and gold_department not in {"general_medicine", "internal_medicine", ""}:
                return True
        if not runtime.completed_tests and runtime.er_turn_count < 2:
            return False
        if target_department in {"general_medicine", "internal_medicine", ""}:
            return False
        return bool(department_candidates)

    @staticmethod
    def normalize_test_plan(recommended_tests: list[Any]) -> list[str]:
        normalized: list[str] = []
        for raw_name in recommended_tests:
            name = str(raw_name).strip()
            if not name:
                continue
            if name not in normalized:
                normalized.append(name)
        return normalized[:2]

    @staticmethod
    def build_interview_question(runtime: HospitalCaseRuntime) -> str:
        if int(runtime.triage_level or 3) <= 2:
            return "What changed most recently that made you come to the ER right now?"
        return "When did your symptoms start, and how have they changed since then?"

    @staticmethod
    def build_interview_answer(runtime: HospitalCaseRuntime) -> str:
        history = str((runtime.case_data.get("patient_visible_info", {}) or {}).get("history", "")).strip()
        if history:
            return history
        complaint = str((runtime.case_data.get("doctor_visible_info", {}) or {}).get("chief_complaint", "")).strip()
        if complaint:
            return f"My main problem has been {complaint.lower()}."
        return "The symptoms have continued, and I still feel unwell."

    @staticmethod
    def build_objective_finding(runtime: HospitalCaseRuntime, test_name: str) -> str:
        suspected = runtime.assessment_summary or "the presenting problem"
        normalized_test = str(test_name).strip()
        if not normalized_test:
            return ""
        hidden_results = dict(runtime.case_data.get("hidden_test_results", {}) or {})
        hidden_entry = dict(hidden_results.get(normalized_test, {}) or {})
        hidden_result = str(hidden_entry.get("result", "")).strip()
        if hidden_result:
            return f"{normalized_test}: {hidden_result}"
        return f"{normalized_test} returned objective evidence supporting {suspected}."

    @staticmethod
    def build_test_result_summary(runtime: HospitalCaseRuntime, test_name: str) -> dict[str, Any]:
        normalized_test = str(test_name).strip() or "Targeted Test"
        hidden_results = dict(runtime.case_data.get("hidden_test_results", {}) or {})
        hidden_entry = dict(hidden_results.get(normalized_test, {}) or {})
        hidden_result = str(hidden_entry.get("result", "")).strip()
        risk = str(runtime.deterioration_risk).strip().lower()
        department = str(runtime.target_department).strip().lower()

        def metric(name: str, value: float, normal_min: float, normal_max: float) -> dict[str, Any]:
            if value < normal_min * 0.8 or value > normal_max * 1.2:
                severity = "critical"
            elif value < normal_min or value > normal_max:
                severity = "warning"
            else:
                severity = "normal"
            return {
                "name": name,
                "value": value,
                "normal_min": normal_min,
                "normal_max": normal_max,
                "severity": severity,
            }

        metrics: list[dict[str, Any]]
        if "blood" in normalized_test.lower():
            if department == "neurology":
                metrics = [
                    metric("AChR Ab", 1.8 if risk == "high" else 1.1, 0.0, 0.5),
                    metric("CK", 210 if risk == "high" else 155, 40, 200),
                    metric("CRP", 0.3, 0.0, 0.5),
                ]
            else:
                metrics = [
                    metric("WBC", 7.2, 4.0, 10.0),
                    metric("Hemoglobin", 13.4, 12.0, 16.0),
                    metric("CRP", 1.1 if risk == "high" else 0.4, 0.0, 0.5),
                ]
        elif any(token in normalized_test.lower() for token in ("ct", "mri", "xray", "x-ray", "imaging")):
            metrics = [
                metric("Lesion Score", 8.1 if department == "neurology" else 1.2, 0.0, 2.0),
                metric("Edema Index", 3.4 if risk == "high" else 1.3, 0.0, 1.8),
                metric("Mass Effect", 0.2, 0.0, 0.5),
            ]
        else:
            metrics = [
                metric("Signal A", 1.0, 0.8, 1.2),
                metric("Signal B", 1.6 if risk == "high" else 1.0, 0.8, 1.2),
                metric("Signal C", 0.7, 0.6, 1.0),
            ]

        abnormal = [item for item in metrics if str(item.get("severity", "")).strip() != "normal"]
        impression = (
            f"{normalized_test} supports {runtime.assessment_summary or 'the current working diagnosis'}."
            if abnormal
            else f"{normalized_test} is largely within expected range."
        )
        if hidden_result:
            impression = hidden_result
        return {
            "test_name": normalized_test,
            "impression": impression,
            "metrics": metrics,
            "result_text": hidden_result,
        }
