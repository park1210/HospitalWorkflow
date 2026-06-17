from __future__ import annotations

import json
from typing import Any

from app.agents.patient_agent import PatientAgent
from app.agents.specialty_agent import SpecialtyAgent
from app.config import settings
from app.core.time_engine import TimeEngine
from app.core.reward import build_step_reward_breakdown, score_step_reward
from app.llm.ollama_client import OllamaClient
from app.core.state import (
    append_known_information,
    record_decision,
    record_decision_snapshot,
    record_consultation,
    record_test_request,
    record_trajectory_step,
    record_what_if_applied,
    record_what_if_event,
)
from app.modules.what_if_module import WhatIfModule
from app.modules.assessment_module import AssessmentModule
from app.modules.diagnostic_handoff_module import DiagnosticHandoffModule
from app.modules.stabilization_module import StabilizationModule
from app.modules.test_module import TestModule
from app.modules.triage_module import TriageModule
from app.utils.ownership_rules import apply_department_ownership_overrides
from app.utils.department_catalog import (
    GENERAL_FALLBACK_DEPARTMENTS,
    build_structured_evidence_profile,
    build_department_candidates,
    choose_department_from_scores,
    combine_department_scores,
    infer_department_scores_from_catalog,
    infer_department_scores_by_source,
    normalize_department,
    prefer_specific_department,
    rank_department_scores,
)
from app.utils.diagnosis_catalog import extract_known_diagnoses, has_direct_diagnosis_support
from app.utils.evidence_summary import build_evidence_summary
from app.utils.prompt_loader import load_prompt


DEFAULT_ER_SYSTEM_PROMPT = """
You are the ER department in a hospital diagnostic workflow simulation.

Your role:
- perform the earliest safe diagnostic workup
- gather the minimum useful history
- request focused objective tests
- decide whether ER can summarize the case or should hand it to another department

Rules:
- prioritize safety and decisive evidence
- do not keep asking repetitive questions
- stop interviewing when objective evidence is already decisive
- request specialty refinement only when ER evidence is still insufficient
- leave a clear rationale for each next action
"""


class ERDepartmentAgent:
    ACTIONS = [
        "ask_patient",
        "await_test_results",
        "observe_patient",
        "perform_triage",
        "perform_assessment",
        "stabilize",
        "request_test",
        "make_diagnostic_summary",
    ]
    ROUTING_REVIEW_GAP = 1.0
    ROUTING_FALLBACK_GAP = 1.5

    def __init__(
        self,
        case: dict[str, Any],
        patient_agent: PatientAgent,
        what_if_override: dict[str, Any] | None = None,
        time_engine: TimeEngine | None = None,
        live_observer: Any | None = None,
    ) -> None:
        self.case = case
        self.patient_agent = patient_agent
        self.what_if_override = dict(what_if_override or {})
        self.client = OllamaClient()
        self.system_prompt = load_prompt("er_department_system.txt", DEFAULT_ER_SYSTEM_PROMPT)
        self._last_llm_action_used = False
        self.triage_module = TriageModule()
        self.assessment_module = AssessmentModule()
        self.stabilization_module = StabilizationModule()
        self.test_module = TestModule(case)
        self.diagnostic_handoff_module = DiagnosticHandoffModule()
        self.what_if_module = WhatIfModule()
        self.specialty_agent = SpecialtyAgent()
        self.time_engine = time_engine or TimeEngine()
        self.live_observer = live_observer

    def _matches_what_if_override(self, node: str, turn_index: int) -> bool:
        if not self.what_if_override or self.what_if_override.get("consumed"):
            return False
        return (
            str(self.what_if_override.get("node", "")).strip() == str(node).strip()
            and int(self.what_if_override.get("turn_index", -1) or -1) == int(turn_index)
        )

    def _apply_what_if_override(
        self,
        state: Any,
        node: str,
        turn_index: int,
        action: str,
        target: str,
        rationale: str,
    ) -> tuple[str, str, str]:
        if not self._matches_what_if_override(node, turn_index):
            return action, target, rationale

        selected_action = dict(self.what_if_override.get("selected_action", {}) or {})
        override_type = str(selected_action.get("type", "")).strip()
        override_target = str(selected_action.get("target", "")).strip()
        if not override_type:
            return action, target, rationale

        if node == "er_next_step":
            applied_action = override_type
            applied_target = override_target
        elif node == "er_routing":
            if override_type == "request_test_before_handoff":
                applied_action = "request_test"
                applied_target = override_target
            elif override_type == "consult_before_handoff":
                applied_action = "consult_before_handoff"
                applied_target = override_target
            else:
                applied_action = action
                applied_target = target
                self.what_if_override["forced_handoff_department"] = override_target
        else:
            applied_action = action
            applied_target = target

        applied_rationale = (
            f"User-selected what-if override at {node}: {override_type}"
            + (f" -> {override_target}" if override_target else "")
        )
        applied_event = {
            "mode": "replay",
            "node": node,
            "turn_index": turn_index,
            "original_action": {"type": action, "target": target, "rationale": rationale},
            "selected_action": {"type": applied_action, "target": applied_target, "rationale": applied_rationale},
            "applied": True,
        }
        record_what_if_applied(state, applied_event)
        self.what_if_override["consumed"] = True
        return applied_action, applied_target, applied_rationale

    def _build_policy_snapshot(self, state_dict: dict[str, Any]) -> dict[str, Any]:
        return {
            "triage_level": int(state_dict.get("triage_level", 3) or 3),
            "is_immediately_unstable": bool(state_dict.get("is_immediately_unstable")),
            "needs_resuscitation_now": bool(state_dict.get("needs_resuscitation_now")),
            "observation_status": str(state_dict.get("observation_status", "")).strip(),
            "next_reassessment_time_min": state_dict.get("next_reassessment_time_min"),
            "working_problem_list": list(state_dict.get("working_problem_list", []))[:4],
            "red_flags": list(state_dict.get("red_flags", []))[:4],
            "stabilization_actions": list(state_dict.get("stabilization_actions", []))[:4],
            "known_information": list(state_dict.get("known_information", []))[-6:],
            "missing_information": list(state_dict.get("missing_information", []))[:5],
            "suspected_diagnoses": list(state_dict.get("suspected_diagnoses", []))[:5],
            "requested_tests": list(state_dict.get("requested_tests", [])),
            "requested_consults": list(state_dict.get("requested_consults", [])),
            "requested_tests_count": len(list(state_dict.get("requested_tests", []))),
            "requested_consults_count": len(list(state_dict.get("requested_consults", []))),
            "objective_findings_count": len(list(state_dict.get("objective_findings", []))),
            "has_objective_evidence": bool(state_dict.get("objective_findings")),
            "er_confidence": float(state_dict.get("er_confidence", 0.0) or 0.0),
            "llm_call_count": int(state_dict.get("llm_call_count", 0) or 0),
            "turn_count": int(state_dict.get("turn_count", 0) or 0),
        }

    def _observation_reassessment_minutes(self) -> int:
        temporal_profile = self.case.get("temporal_profile", {})
        if isinstance(temporal_profile, dict):
            value = temporal_profile.get("observation_reassessment_minutes")
            if value is not None:
                return max(5, int(value or 0))
        return 15

    def _should_observe_before_handoff(
        self,
        state: dict[str, Any],
        *,
        patient_turns: int,
        objective_findings: list[str],
        remaining_tests: list[str],
        pending_wait: int | None,
        routing_analysis: dict[str, Any],
        working_diagnosis: str,
    ) -> bool:
        if state.get("is_immediately_unstable") or state.get("needs_resuscitation_now"):
            return False
        if remaining_tests or (pending_wait is not None and pending_wait > 0):
            return False
        if objective_findings:
            return False
        if patient_turns < 2:
            return False
        observation_status = str(state.get("observation_status", "")).strip().lower()
        if observation_status in {"completed", "reassessed"}:
            return False
        if not self._is_generic_working_diagnosis(working_diagnosis):
            return False
        routing_candidates = list(routing_analysis.get("routing_candidates", []) or [])
        chosen_department = normalize_department(
            str(routing_analysis.get("chosen_department", "")).strip(),
            default="general_medicine",
        )
        if routing_candidates and chosen_department not in GENERAL_FALLBACK_DEPARTMENTS:
            return False
        return True

    def _clean_question(self, text: str) -> str:
        question = str(text).strip()
        if question.startswith('"') and question.endswith('"') and len(question) >= 2:
            question = question[1:-1].strip()
        return question

    def _emit_live_update(
        self,
        state: Any,
        transcript: list[dict[str, str]],
        *,
        phase: str,
        action: str,
        target: str = "",
        conversation_lines: list[str] | None = None,
    ) -> None:
        if not callable(self.live_observer):
            return
        self.live_observer(
            {
                "case_id": str(getattr(state, "case_id", "")).strip(),
                "phase": phase,
                "actor": "er_department",
                "action": str(action).strip(),
                "target": str(target).strip(),
                "state": state.to_dict(),
                "transcript_tail": list(transcript[-6:]),
                "conversation_lines": list(conversation_lines or []),
            }
        )

    def _record_step_and_emit(
        self,
        state: Any,
        transcript: list[dict[str, str]],
        step_entry: dict[str, Any],
        conversation_lines: list[str] | None = None,
    ) -> None:
        record_trajectory_step(state, step_entry)
        self._emit_live_update(
            state,
            transcript,
            phase="er_step",
            action=str(step_entry.get("action", "")).strip(),
            target=str(step_entry.get("target", "")).strip(),
            conversation_lines=conversation_lines,
        )

    def _ask_patient_question(self, state: dict[str, Any], transcript: list[dict[str, str]]) -> str:
        missing = list(state.get("missing_information", []) or [])
        known = " ".join(state.get("known_information", []) or []).lower()
        asked_questions = {
            " ".join(str(entry.get("content", "")).strip().lower().split())
            for entry in transcript
            if entry.get("role") == "er_interview"
        }

        candidate_questions: list[tuple[str, str]] = [
            ("symptom onset and duration", "When did your symptoms start, and how have they changed since then?"),
            ("associated symptoms", "Have you noticed any other symptoms along with this problem?"),
            ("aggravating or relieving factors", "Does anything make it better or worse?"),
        ]
        for missing_item, question in candidate_questions:
            if missing_item in missing:
                normalized = " ".join(question.strip().lower().split())
                if normalized not in asked_questions:
                    return question

        fallback_questions: list[str] = []
        if "abdominal" in known:
            fallback_questions.extend(
                [
                    "Can you point to where the pain is strongest?",
                    "Has the pain moved or spread anywhere else?",
                ]
            )
        if "double vision" in known or "diplopia" in known:
            fallback_questions.extend(
                [
                    "Do your symptoms get worse with activity or improve with rest?",
                    "Do the weakness or vision changes fluctuate during the day?",
                ]
            )
        if "chest pain" in known:
            fallback_questions.extend(
                [
                    "When did the chest discomfort start, and does it happen with activity or at rest?",
                    "Does the chest discomfort spread anywhere or come with shortness of breath?",
                ]
            )
        fallback_questions.extend(
            [
                "Can you tell me a bit more about what has been going on?",
                "What change in your symptoms has concerned you the most?",
                "Has anything about this been getting better or worse recently?",
            ]
        )
        for question in fallback_questions:
            normalized = " ".join(question.strip().lower().split())
            if normalized not in asked_questions:
                return question
        return "What else about these symptoms do you think is important for us to know?"

    def _build_department_routing_scores(self, state: dict[str, Any], transcript: list[dict[str, str]]) -> dict[str, float]:
        return self._build_department_routing_analysis(state, transcript)["final_scores_raw"]

    def _compact_score_map(self, score_map: dict[str, float], limit: int = 5) -> dict[str, float]:
        return {
            department: round(float(score), 3)
            for department, score in rank_department_scores(score_map)[:limit]
            if float(score) > 0
        }

    def _build_department_routing_inputs(self, state: dict[str, Any], transcript: list[dict[str, str]]) -> tuple[dict[str, Any], dict[str, Any], str]:
        evidence_summary = build_evidence_summary(state, transcript)
        working_diagnosis = self._determine_working_diagnosis(state, transcript)
        source_payload = {
            "working_diagnosis": working_diagnosis,
            "objective_findings": evidence_summary.get("positive_or_supporting", []),
            "chief_complaint": str(state.get("arrival_info", "")).strip(),
            "history": " ".join(
                str(item).strip()
                for item in state.get("known_information", [])[-6:]
                if str(item).strip()
            ),
            "known_information": [
                *evidence_summary.get("negative_or_excluding", []),
                *evidence_summary.get("medication_or_exposure", []),
                *(str(item).strip() for item in state.get("known_information", [])[-4:] if str(item).strip()),
            ],
            "working_problem_list": [str(item).strip() for item in state.get("working_problem_list", []) if str(item).strip()],
        }
        evidence_text = " ".join(
            [
                working_diagnosis,
                *evidence_summary.get("positive_or_supporting", []),
                *evidence_summary.get("negative_or_excluding", []),
                *[str(item).strip() for item in state.get("known_information", [])[-4:] if str(item).strip()],
            ]
        ).lower()
        return source_payload, evidence_summary, evidence_text

    def _apply_er_ownership_overrides(self, score_map: dict[str, float], evidence_text: str) -> tuple[dict[str, float], list[str]]:
        return apply_department_ownership_overrides(score_map, evidence_text)

    def _build_department_routing_analysis(self, state: dict[str, Any], transcript: list[dict[str, str]]) -> dict[str, Any]:
        source_payload, evidence_summary, evidence_text = self._build_department_routing_inputs(state, transcript)
        source_score_breakdown: dict[str, dict[str, float]] = {}
        for source_name, raw_value in source_payload.items():
            scores = infer_department_scores_by_source({source_name: raw_value}, prefer_clinical_department=True)
            compact = self._compact_score_map(scores)
            if compact:
                source_score_breakdown[source_name] = compact

        evidence_scores = infer_department_scores_by_source(source_payload, prefer_clinical_department=True)
        assessment_scores = {str(k).strip(): float(v) for k, v in (state.get("candidate_scores", {}) or {}).items() if str(k).strip()}
        structured_profile = build_structured_evidence_profile(
            working_diagnosis=str(source_payload.get("working_diagnosis", "")).strip(),
            chief_complaint=str(source_payload.get("chief_complaint", "")).strip(),
            history=str(source_payload.get("history", "")).strip(),
            objective_findings=evidence_summary.get("positive_or_supporting", []),
            known_information=[str(item).strip() for item in state.get("known_information", [])[-6:] if str(item).strip()],
            assessment_family_scores={str(k).strip(): float(v) for k, v in (state.get("family_signal_scores", {}) or {}).items() if str(k).strip()},
        )
        catalog_scores = infer_department_scores_from_catalog(evidence_text, limit=6, min_score=0.34)
        combined_scores = combine_department_scores(
            evidence_scores,
            assessment_scores,
            catalog_scores,
            dict(structured_profile.get("exact_department_scores", {}) or {}),
            dict(structured_profile.get("family_department_scores", {}) or {}),
        )
        combined_scores, override_notes = self._apply_er_ownership_overrides(combined_scores, evidence_text)
        initially_chosen_department = choose_department_from_scores(
            combined_scores,
            default="general_medicine",
            fallback_if_ambiguous="internal_medicine",
            ambiguity_margin=1.5,
            low_confidence_threshold=1.5,
        )
        initially_chosen_department = prefer_specific_department(combined_scores, initially_chosen_department)
        chosen_department, routing_review = self._review_routing_decision(
            working_diagnosis=str(source_payload.get("working_diagnosis", "")).strip(),
            objective_findings=evidence_summary.get("positive_or_supporting", []),
            combined_scores=combined_scores,
            source_score_breakdown=source_score_breakdown,
            structured_profile=structured_profile,
            initially_chosen_department=initially_chosen_department,
        )
        chosen_department = normalize_department(chosen_department, default="general_medicine")
        routing_candidates = build_department_candidates(combined_scores, limit=2)
        top_evidence = [
            *[str(item).strip() for item in evidence_summary.get("positive_or_supporting", [])[:3] if str(item).strip()],
            *[str(item).strip() for item in evidence_summary.get("medication_or_exposure", [])[:2] if str(item).strip()],
        ][:4]
        top_sources = [name for name, values in source_score_breakdown.items() if chosen_department in values][:2]
        rationale_bits = []
        if top_sources:
            rationale_bits.append(f"{chosen_department} was mainly supported by {', '.join(top_sources)}")
        if override_notes:
            rationale_bits.append(f"override applied: {override_notes[0]}")
        if routing_candidates:
            rationale_bits.append(f"top shortlist: {routing_candidates}")
        if routing_review.get("review_applied"):
            rationale_bits.append(str(routing_review.get("review_reason", "")).strip())
        return {
            "working_diagnosis": str(source_payload.get('working_diagnosis', '')).strip(),
            "dominant_family": str(structured_profile.get("dominant_family", "")).strip(),
            "family_score_breakdown": self._compact_score_map(dict(structured_profile.get("family_scores", {}) or {})),
            "family_department_score_breakdown": self._compact_score_map(dict(structured_profile.get("family_department_scores", {}) or {})),
            "exact_diagnosis_hits": list(structured_profile.get("exact_diagnosis_hits", []) or []),
            "exact_department_score_breakdown": self._compact_score_map(dict(structured_profile.get("exact_department_scores", {}) or {})),
            "top_evidence": top_evidence,
            "source_score_breakdown": source_score_breakdown,
            "assessment_score_breakdown": self._compact_score_map(assessment_scores),
            "catalog_score_breakdown": self._compact_score_map(catalog_scores),
            "final_scores": self._compact_score_map(combined_scores),
            "final_scores_raw": combined_scores,
            "routing_candidates": routing_candidates,
            "routing_review": routing_review,
            "chosen_department": chosen_department,
            "override_notes": override_notes,
            "rationale": ". ".join(rationale_bits).strip(),
        }

    def _is_generic_working_diagnosis(self, diagnosis: str) -> bool:
        normalized = str(diagnosis).strip().lower()
        if not normalized:
            return True
        generic_prefixes = (
            "possible ",
            "undifferentiated",
            "acute abdominal",
            "possible acute",
            "possible central",
            "possible multisystem",
            "possible systemic",
            "possible infectious",
            "possible pulmonary",
            "possible cardiac",
            "possible urinary",
            "possible gynecologic",
            "possible bowel",
            "possible structural",
            "possible cerebellar",
            "possible neuromuscular junction",
            "possible neurologic process",
            "possible respiratory",
            "possible cardiovascular",
        )
        return any(normalized.startswith(prefix) for prefix in generic_prefixes)

    def _department_ownership_signal(
        self,
        department: str,
        source_score_breakdown: dict[str, dict[str, float]],
        structured_profile: dict[str, Any],
    ) -> float:
        normalized = normalize_department(department, default="")
        if not normalized:
            return 0.0
        exact_scores = dict(structured_profile.get("exact_department_scores", {}) or {})
        family_scores = dict(structured_profile.get("family_department_scores", {}) or {})
        signal = float(exact_scores.get(normalized, 0.0) or 0.0) + float(family_scores.get(normalized, 0.0) or 0.0)
        for source_name in ("objective_findings", "history", "known_information", "chief_complaint", "consult_opinions"):
            signal += float((source_score_breakdown.get(source_name, {}) or {}).get(normalized, 0.0) or 0.0)
        return round(signal, 4)

    def _review_routing_decision(
        self,
        *,
        working_diagnosis: str,
        objective_findings: list[str],
        combined_scores: dict[str, float],
        source_score_breakdown: dict[str, dict[str, float]],
        structured_profile: dict[str, Any],
        initially_chosen_department: str,
    ) -> tuple[str, dict[str, Any]]:
        ranked = rank_department_scores(combined_scores)
        normalized_initial = normalize_department(initially_chosen_department, default="general_medicine")
        top_candidates = build_department_candidates(combined_scores, limit=2)
        generic_working_diagnosis = self._is_generic_working_diagnosis(working_diagnosis)
        objective_count = len([item for item in objective_findings if str(item).strip()])
        score_margin = 999.0
        top1_department = normalize_department(ranked[0][0], default=normalized_initial) if ranked else normalized_initial
        top2_department = ""
        if len(ranked) > 1:
            top2_department = normalize_department(ranked[1][0], default="")
            score_margin = round(float(ranked[0][1]) - float(ranked[1][1]), 4)

        review = {
            "initially_chosen_department": normalized_initial,
            "score_margin_top1_top2": score_margin if score_margin != 999.0 else None,
            "generic_working_diagnosis": generic_working_diagnosis,
            "objective_findings_count": objective_count,
            "top1_department": top1_department,
            "top2_department": top2_department,
            "top_candidates": top_candidates,
            "review_applied": False,
            "review_reason": "",
            "ownership_signals": {},
        }
        if not top2_department:
            return normalized_initial, review

        top1_ownership = self._department_ownership_signal(top1_department, source_score_breakdown, structured_profile)
        top2_ownership = self._department_ownership_signal(top2_department, source_score_breakdown, structured_profile)
        review["ownership_signals"] = {
            top1_department: top1_ownership,
            top2_department: top2_ownership,
        }

        if (
            generic_working_diagnosis
            and objective_count >= 2
            and score_margin < self.ROUTING_REVIEW_GAP
            and top2_ownership > (top1_ownership + 0.25)
        ):
            review["review_applied"] = True
            review["review_reason"] = (
                f"routing review favored {top2_department} because the working diagnosis stayed generic, "
                "objective evidence was already available, and the alternative specialty ownership signal was stronger."
            )
            return top2_department, review

        if (
            normalize_department(normalized_initial, default="") in GENERAL_FALLBACK_DEPARTMENTS
            and score_margin < self.ROUTING_FALLBACK_GAP
            and top2_ownership >= top1_ownership
        ):
            review["review_applied"] = True
            review["review_reason"] = (
                f"routing review replaced fallback routing with {top2_department} because a specific specialty alternative "
                "had at least comparable ownership support."
            )
            return top2_department, review

        return normalized_initial, review

    def _determine_target_department(self, state: dict[str, Any], transcript: list[dict[str, str]]) -> str:
        analysis = self._build_department_routing_analysis(state, transcript)
        return normalize_department(str(analysis.get("chosen_department", "")).strip(), default="general_medicine")

    def _determine_working_diagnosis(self, state: dict[str, Any], transcript: list[dict[str, str]]) -> str:
        objective_findings = list(state.get("objective_findings", []) or [])
        if objective_findings:
            objective_text = "\n".join(str(item).strip() for item in objective_findings if str(item).strip())
            extracted = extract_known_diagnoses(objective_text, limit=1)
            if extracted and has_direct_diagnosis_support(objective_text, extracted[0]):
                return extracted[0]
        suspected = [str(item).strip() for item in state.get("suspected_diagnoses", []) if str(item).strip()]
        if suspected:
            return suspected[0]
        working_problem_list = [str(item).strip() for item in state.get("working_problem_list", []) if str(item).strip()]
        return working_problem_list[0] if working_problem_list else ""

    def _is_resolved_in_er(self, working_diagnosis: str, objective_findings: list[str]) -> bool:
        diagnosis = str(working_diagnosis).strip().lower()
        if not diagnosis or not objective_findings:
            return False
        generic_prefixes = (
            "possible ",
            "undifferentiated",
            "acute abdominal",
            "possible acute",
            "possible central",
            "possible multisystem",
            "possible systemic",
            "possible infectious",
            "possible pulmonary",
            "possible cardiac",
            "possible urinary",
            "possible gynecologic",
            "possible bowel",
            "possible structural",
            "possible cerebellar",
            "possible neuromuscular junction",
            "possible neurologic process",
        )
        return not any(diagnosis.startswith(prefix) for prefix in generic_prefixes)

    def _llm_choose_next_action(self, state: dict[str, Any], transcript: list[dict[str, str]]) -> tuple[str, str, str] | None:
        self._last_llm_action_used = False
        if not settings.USE_LLM_FOR_ER_DEPARTMENT_AGENT:
            return None

        payload = {
            "role": "er_department",
            "allowed_actions": ["ask_patient", "make_diagnostic_summary"],
            "state_snapshot": self._build_policy_snapshot(state),
            "working_problem_list": list(state.get("working_problem_list", []))[:4],
            "objective_findings": list(state.get("objective_findings", []))[-4:],
            "known_information": list(state.get("known_information", []))[-6:],
            "recent_transcript": transcript[-8:],
            "instruction": (
                "Return JSON with keys action, target, rationale. "
                "Choose only one of ask_patient or make_diagnostic_summary. "
                "Use ask_patient only when one more focused question is likely to change the handoff decision."
            ),
        }
        try:
            response = self.client.chat(
                self.system_prompt,
                json.dumps(payload, ensure_ascii=False, indent=2),
            ).strip()
            parsed = json.loads(response)
        except Exception:
            return None

        action = str(parsed.get("action", "")).strip()
        target = str(parsed.get("target", "")).strip()
        rationale = str(parsed.get("rationale", "")).strip()
        if action not in {"ask_patient", "make_diagnostic_summary"}:
            return None
        if action == "ask_patient" and state.get("objective_findings"):
            return None
        if not rationale:
            return None
        self._last_llm_action_used = True
        return action, target, rationale

    def _choose_next_action(self, state: dict[str, Any], transcript: list[dict[str, str]]) -> tuple[str, str, str]:
        self._last_llm_action_used = False
        self.time_engine.release_ready_results(state)
        observation_status = str(state.get("observation_status", "")).strip().lower()
        next_reassessment_time_min = state.get("next_reassessment_time_min")
        current_time_min = int(state.get("current_time_min", 0) or 0)
        if (
            observation_status in {"under_observation", "reassessment_due"}
            and next_reassessment_time_min is not None
            and current_time_min >= int(next_reassessment_time_min or 0)
        ):
            state["observation_status"] = "reassessment_due"
            return "perform_assessment", "", "The observation interval is complete, so the ER should reassess before deciding on handoff."
        if not state.get("triage_rationale"):
            return "perform_triage", "", "The ER has not triaged this patient yet."
        if not state.get("working_problem_list"):
            return "perform_assessment", "", "The ER needs an initial assessment before choosing tests or a diagnostic handoff."
        if state.get("needs_resuscitation_now") and not state.get("stabilization_actions"):
            return "stabilize", "", "The patient is unstable, so stabilization should happen before further workup."

        patient_turns = sum(1 for entry in transcript if entry.get("role") == "patient")
        objective_findings = list(state.get("objective_findings", []) or [])
        requested_tests = set(str(item).strip() for item in state.get("requested_tests", []) if str(item).strip())
        recommended_tests = [str(item).strip() for item in state.get("recommended_tests", []) if str(item).strip()]
        remaining_tests = [item for item in recommended_tests if item not in requested_tests]
        routing_analysis = self._build_department_routing_analysis(state, transcript)
        combined_scores = dict(routing_analysis.get("final_scores_raw", {}) or {})
        target_department = normalize_department(str(routing_analysis.get("chosen_department", "")).strip(), default="general_medicine")
        working_diagnosis = self._determine_working_diagnosis(state, transcript)
        confidence = 0.2
        if objective_findings:
            confidence += 0.3
        if working_diagnosis:
            confidence += 0.15
        confidence = min(confidence, 0.9)

        state["responsible_department"] = target_department
        state["department_routing_candidates"] = list(routing_analysis.get("routing_candidates", []) or [])
        state["department_routing_scores"] = combined_scores
        state["er_routing_analysis"] = {
            key: value for key, value in routing_analysis.items() if key != "final_scores_raw"
        }
        state["er_working_diagnosis"] = working_diagnosis
        state["er_confidence"] = confidence

        if patient_turns < 2 and not objective_findings and not state.get("is_immediately_unstable"):
            return "ask_patient", "", "The ER still needs a minimum history before moving to tests or handoff."

        if remaining_tests:
            return "request_test", remaining_tests[0], "The ER needs objective data before deciding on specialty responsibility or the next diagnostic handoff."

        pending_wait = self.time_engine.next_pending_result_wait(state)
        if pending_wait is not None and pending_wait > 0:
            return "await_test_results", "", "Key objective results are still pending, so the ER should wait for those results before escalating."

        if self._should_observe_before_handoff(
            state,
            patient_turns=patient_turns,
            objective_findings=objective_findings,
            remaining_tests=remaining_tests,
            pending_wait=pending_wait,
            routing_analysis=routing_analysis,
            working_diagnosis=working_diagnosis,
        ):
            return "observe_patient", "", "Current evidence is still too sparse for a useful specialty handoff, so a short ER observation interval with reassessment is justified."

        if self._is_resolved_in_er(working_diagnosis, objective_findings):
            return "make_diagnostic_summary", "", "The ER already has decisive objective evidence, so the case can be summarized without an extra specialty handoff."

        llm_choice = self._llm_choose_next_action(state, transcript)
        if llm_choice is not None:
            return llm_choice

        return "make_diagnostic_summary", "", "The ER has gathered enough initial evidence; because uncertainty remains, the next useful step is a direct specialty handoff."

    def _sync_state_after_decision(self, state: Any, action: str, target: str, rationale: str) -> None:
        state.next_action = action
        state.latest_rationale = rationale

    def run(self, state: Any, transcript: list[dict[str, str]], max_turns: int) -> None:
        triage_result = self.triage_module.run(self.case)
        state.triage_level = int(triage_result.get("triage_level", 3) or 3)
        state.triage_rationale = str(triage_result.get("triage_rationale", "")).strip()
        state.is_immediately_unstable = bool(triage_result.get("is_unstable"))
        state.needs_resuscitation_now = bool(triage_result.get("needs_resuscitation_now"))
        state.red_flags = [str(item).strip() for item in triage_result.get("red_flags", []) if str(item).strip()]
        append_known_information(state, f"Triage level {state.triage_level}")
        transcript.append({"role": "triage_module", "content": str(triage_result)})
        record_decision(state, "er_department", "perform_triage", state.triage_rationale)
        self.time_engine.advance_time(
            self.case,
            state,
            actor="er_department",
            action="perform_triage",
            rationale=state.triage_rationale,
        )

        assessment_result = self.assessment_module.run(self.case, state.to_dict())
        state.working_problem_list = [str(item).strip() for item in assessment_result.get("working_problem_list", []) if str(item).strip()]
        state.recommended_tests = [str(item).strip() for item in assessment_result.get("recommended_initial_tests", []) if str(item).strip()]
        state.candidate_scores = {
            str(key).strip(): float(value)
            for key, value in (assessment_result.get("department_signal_scores", {}) or {}).items()
            if str(key).strip()
        }
        state.family_signal_scores = {
            str(key).strip(): float(value)
            for key, value in (assessment_result.get("family_signal_scores", {}) or {}).items()
            if str(key).strip()
        }
        state.suspected_system = str(assessment_result.get("suspected_system", "")).strip()
        state.department_routing_scores = dict(state.candidate_scores)
        state.red_flags.extend(
            str(item).strip()
            for item in assessment_result.get("red_flags", [])
            if str(item).strip() and str(item).strip() not in state.red_flags
        )
        append_known_information(state, "ER assessment completed")
        transcript.append({"role": "assessment_module", "content": str(assessment_result)})
        record_decision(state, "er_department", "perform_assessment", str(assessment_result.get("assessment_rationale", "")).strip())
        self.time_engine.advance_time(
            self.case,
            state,
            actor="er_department",
            action="perform_assessment",
            rationale=str(assessment_result.get("assessment_rationale", "")).strip(),
        )
        if str(state.observation_status).strip().lower() in {"under_observation", "reassessment_due"}:
            state.observation_status = "completed"
            state.next_reassessment_time_min = None
            append_known_information(state, "ER observation interval completed and reassessment performed.")

        if state.needs_resuscitation_now or state.is_immediately_unstable:
            stabilization_result = self.stabilization_module.run(self.case, state.to_dict())
            state.stabilization_actions = [
                str(item).strip()
                for item in stabilization_result.get("stabilization_actions", [])
                if str(item).strip()
            ]
            state.stabilized_after_intervention = bool(stabilization_result.get("stabilized_after_intervention", True))
            transcript.append({"role": "stabilization_module", "content": str(stabilization_result)})
            record_decision(state, "er_department", "stabilize", str(stabilization_result.get("post_stabilization_status", "")).strip())
            self.time_engine.advance_time(
                self.case,
                state,
                actor="er_department",
                action="stabilize",
                rationale=str(stabilization_result.get("post_stabilization_status", "")).strip(),
            )

        for _ in range(max_turns):
            state.turn_count += 1
            released_results = self.time_engine.release_ready_results(state)
            if released_results:
                transcript.append(
                    {
                        "role": "time_engine",
                        "content": f"Released {len(released_results)} pending test result(s) before the next ER decision.",
                    }
                )
            action, target, rationale = self._choose_next_action(state.to_dict(), transcript)
            used_er_llm = self._last_llm_action_used
            if used_er_llm:
                state.llm_call_count += 1
            routing_analysis = self._build_department_routing_analysis(state.to_dict(), transcript)
            state.er_routing_analysis = {
                key: value for key, value in routing_analysis.items() if key != "final_scores_raw"
            }
            state.department_routing_candidates = list(routing_analysis.get("routing_candidates", []) or state.department_routing_candidates)
            state.department_routing_scores = dict(routing_analysis.get("final_scores_raw", {}) or state.department_routing_scores)
            if routing_analysis.get("working_diagnosis"):
                state.er_working_diagnosis = str(routing_analysis.get("working_diagnosis", "")).strip() or state.er_working_diagnosis
            if routing_analysis.get("chosen_department"):
                state.responsible_department = normalize_department(
                    str(routing_analysis.get("chosen_department", "")).strip(),
                    default=state.responsible_department or "general_medicine",
                )
            snapshot = self.what_if_module.build_er_next_step_snapshot(
                state_dict=state.to_dict(),
                transcript=transcript,
                proposed_action=action,
                proposed_target=target,
                proposed_rationale=rationale,
                turn_index=state.turn_count,
                case_id=state.case_id,
            )
            record_decision_snapshot(state, snapshot)
            action, target, rationale = self._apply_what_if_override(
                state,
                "er_next_step",
                state.turn_count,
                action,
                target,
                rationale,
            )
            self._sync_state_after_decision(state, action, target, rationale)
            record_decision(state, "er_department", action, rationale)
            if settings.USE_WHAT_IF_SHADOW:
                what_if_event = self.what_if_module.evaluate_er_next_step_shadow(
                    state.to_dict(),
                    routing_analysis,
                    action,
                    target,
                    rationale,
                )
                what_if_event["case_id"] = state.case_id
                what_if_event["turn_index"] = state.turn_count
                record_what_if_event(state, what_if_event)
                state.counterfactual_action_candidates = list(what_if_event.get("alternatives", []) or [])
                transcript.append({"role": "what_if_shadow", "content": str(what_if_event)})

            step_reward_breakdown = build_step_reward_breakdown(
                action,
                state_snapshot=self._build_policy_snapshot(state.to_dict()),
                target=target,
                used_reasoning_llm=False,
                used_reflection_llm=False,
            )
            step_entry = {
                "turn_index": state.turn_count,
                "observation": self._build_policy_snapshot(state.to_dict()),
                "reasoning_output": {
                    "next_action": action,
                    "suspected_diagnoses": list(state.suspected_diagnoses),
                    "recommended_tests": list(state.recommended_tests),
                    "target_department": state.responsible_department,
                    "final_diagnosis_if_ready": state.er_working_diagnosis,
                    "final_department_if_ready": state.responsible_department,
                    "confidence": state.er_confidence,
                    "er_routing_analysis": state.er_routing_analysis,
                },
                "action": action,
                "target": target,
                "decision_rationale": rationale,
                "used_reasoning_llm": used_er_llm,
                "evidence_summary": build_evidence_summary(state.to_dict(), transcript),
                "immediate_reward_breakdown": step_reward_breakdown,
                "immediate_reward": round(score_step_reward(step_reward_breakdown), 4),
                "outcome": {},
            }

            if action == "ask_patient":
                question = self._clean_question(self._ask_patient_question(state.to_dict(), transcript))
                answer = self.patient_agent.answer(question)
                transcript.append({"role": "er_interview", "content": question})
                transcript.append({"role": "patient", "content": answer})
                append_known_information(state, answer)
                state.missing_information = [item for item in state.missing_information if item not in {"symptom onset and duration", "associated symptoms", "aggravating or relieving factors"}]
                time_result = self.time_engine.advance_time(
                    self.case,
                    state,
                    actor="er_department",
                    action="ask_patient",
                    rationale=rationale,
                )
                step_entry["outcome"] = {"question": question, "answer": answer}
                step_entry["time"] = time_result
                self._record_step_and_emit(
                    state,
                    transcript,
                    step_entry,
                    conversation_lines=[
                        f"ER: {question}",
                        f"Patient: {answer}",
                    ],
                )
                continue

            if action == "await_test_results":
                wait_min = self.time_engine.next_pending_result_wait(state) or 0
                time_result = self.time_engine.advance_passive_time(
                    self.case,
                    state,
                    minutes=wait_min,
                    reason=rationale,
                    action="await_test_results",
                )
                released = self.time_engine.release_ready_results(state)
                transcript.append(
                    {
                        "role": "time_engine",
                        "content": f"Awaited pending test results for {wait_min} minutes; released {len(released)} result(s).",
                    }
                )
                step_entry["outcome"] = {
                    "waited_for_pending_results_min": wait_min,
                    "released_results": released,
                }
                step_entry["time"] = time_result
                self._record_step_and_emit(state, transcript, step_entry)
                continue

            if action == "perform_assessment":
                assessment_result = self.assessment_module.run(self.case, state.to_dict())
                state.working_problem_list = [
                    str(item).strip()
                    for item in assessment_result.get("working_problem_list", [])
                    if str(item).strip()
                ] or state.working_problem_list
                state.suspected_system = str(assessment_result.get("suspected_system", "")).strip()
                state.suspected_diagnoses = [
                    str(item).strip()
                    for item in assessment_result.get("suspected_diagnoses", [])
                    if str(item).strip()
                ]
                state.recommended_tests = [
                    str(item).strip()
                    for item in assessment_result.get("recommended_initial_tests", [])
                    if str(item).strip()
                ]
                state.red_flags = [
                    *state.red_flags,
                    *(
                        str(item).strip()
                        for item in assessment_result.get("red_flags", [])
                        if str(item).strip() and str(item).strip() not in state.red_flags
                    ),
                ]
                append_known_information(state, "ER reassessment completed")
                state.observation_status = "completed"
                state.next_reassessment_time_min = None
                transcript.append({"role": "assessment_module", "content": str(assessment_result)})
                time_result = self.time_engine.advance_time(
                    self.case,
                    state,
                    actor="er_department",
                    action="perform_assessment",
                    rationale=rationale,
                )
                step_entry["outcome"] = assessment_result
                step_entry["time"] = time_result
                self._record_step_and_emit(state, transcript, step_entry)
                continue

            if action == "observe_patient":
                observation_minutes = self._observation_reassessment_minutes()
                state.observation_status = "under_observation"
                state.next_reassessment_time_min = int(state.current_time_min or 0) + observation_minutes
                time_result = self.time_engine.advance_passive_time(
                    self.case,
                    state,
                    minutes=observation_minutes,
                    reason=rationale,
                    action="observe_patient",
                )
                transcript.append(
                    {
                        "role": "observation_module",
                        "content": (
                            f"Observed in ER for {observation_minutes} minutes; reassessment due at minute "
                            f"{state.next_reassessment_time_min}."
                        ),
                    }
                )
                step_entry["outcome"] = {
                    "observation_minutes": observation_minutes,
                    "reassessment_due_min": state.next_reassessment_time_min,
                }
                step_entry["time"] = time_result
                self._record_step_and_emit(state, transcript, step_entry)
                continue

            if action == "request_test":
                record_test_request(state, target)
                resolved_name, result_text = self.test_module.request_test(target)
                time_result = self.time_engine.advance_time(
                    self.case,
                    state,
                    actor="er_department",
                    action="request_test",
                    target=resolved_name or target,
                    rationale=rationale,
                )
                pending_result = self.time_engine.schedule_pending_result(
                    state,
                    requested_test=target,
                    resolved_name=resolved_name or target,
                    result_text=result_text,
                    pending_result_plan=dict(time_result.get("pending_result_plan", {}) or {}),
                )
                transcript.append(
                    {
                        "role": "test_module",
                        "content": f"{resolved_name or target} ordered; result pending until minute {pending_result['ready_time_min']}.",
                    }
                )
                step_entry["outcome"] = {
                    "requested_test": target,
                    "resolved_name": resolved_name or target,
                    "result_pending": True,
                    "ready_time_min": pending_result["ready_time_min"],
                }
                step_entry["time"] = time_result
                self._record_step_and_emit(state, transcript, step_entry)
                continue

            if action == "make_diagnostic_summary":
                routing_snapshot = self.what_if_module.build_er_routing_snapshot(
                    state_dict=state.to_dict(),
                    transcript=transcript,
                    routing_analysis=routing_analysis,
                    turn_index=state.turn_count,
                    case_id=state.case_id,
                )
                record_decision_snapshot(state, routing_snapshot)
                if settings.USE_WHAT_IF_SHADOW:
                    routing_event = self.what_if_module.evaluate_er_routing_shadow(
                        state.to_dict(),
                        routing_analysis,
                    )
                    routing_event["case_id"] = state.case_id
                    routing_event["turn_index"] = state.turn_count
                    record_what_if_event(state, routing_event)
                    transcript.append({"role": "what_if_shadow", "content": str(routing_event)})
                action, target, rationale = self._apply_what_if_override(
                    state,
                    "er_routing",
                    state.turn_count,
                    action,
                    target,
                    rationale,
                )
                if action == "request_test":
                    if state.decision_history:
                        state.decision_history[-1] = {
                            "actor": "er_department",
                            "action": action,
                            "rationale": rationale,
                        }
                    state.latest_rationale = rationale
                    state.next_action = action
                    record_test_request(state, target)
                    resolved_name, result_text = self.test_module.request_test(target)
                    time_result = self.time_engine.advance_time(
                        self.case,
                        state,
                        actor="er_department",
                        action="request_test",
                        target=resolved_name or target,
                        rationale=rationale,
                    )
                    pending_result = self.time_engine.schedule_pending_result(
                        state,
                        requested_test=target,
                        resolved_name=resolved_name or target,
                        result_text=result_text,
                        pending_result_plan=dict(time_result.get("pending_result_plan", {}) or {}),
                    )
                    transcript.append(
                        {
                            "role": "test_module",
                            "content": f"{resolved_name or target} ordered; result pending until minute {pending_result['ready_time_min']}.",
                        }
                    )
                    step_entry["action"] = action
                    step_entry["target"] = target
                    step_entry["decision_rationale"] = rationale
                    step_entry["outcome"] = {
                        "requested_test": target,
                        "resolved_name": resolved_name or target,
                        "result_pending": True,
                        "ready_time_min": pending_result["ready_time_min"],
                        "what_if_override_applied": True,
                    }
                    step_entry["time"] = time_result
                    self._record_step_and_emit(state, transcript, step_entry)
                    continue
                if action == "consult_before_handoff":
                    if state.decision_history:
                        state.decision_history[-1] = {
                            "actor": "er_department",
                            "action": action,
                            "rationale": rationale,
                        }
                    state.latest_rationale = rationale
                    state.next_action = action
                    consult_department = normalize_department(target, default=target or "general_medicine")
                    opinion = self.specialty_agent.consult(consult_department, state.to_dict(), transcript)
                    record_consultation(state, consult_department, opinion)
                    append_known_information(state, f"{consult_department} consult: {opinion}")
                    transcript.append(
                        {
                            "role": f"{consult_department}_consult",
                            "content": opinion,
                        }
                    )
                    rerouted_analysis = self._build_department_routing_analysis(state.to_dict(), transcript)
                    state.er_routing_analysis = {
                        key: value for key, value in rerouted_analysis.items() if key != "final_scores_raw"
                    }
                    state.department_routing_candidates = list(rerouted_analysis.get("routing_candidates", []) or [])
                    state.department_routing_scores = dict(rerouted_analysis.get("final_scores_raw", {}) or {})
                    if rerouted_analysis.get("working_diagnosis"):
                        state.er_working_diagnosis = str(rerouted_analysis.get("working_diagnosis", "")).strip() or state.er_working_diagnosis
                    if rerouted_analysis.get("chosen_department"):
                        state.responsible_department = normalize_department(
                            str(rerouted_analysis.get("chosen_department", "")).strip(),
                            default=state.responsible_department or "general_medicine",
                        )
                    time_result = self.time_engine.advance_time(
                        self.case,
                        state,
                        actor="er_department",
                        action="consult_before_handoff",
                        target=consult_department,
                        rationale=rationale,
                    )
                    step_entry["action"] = action
                    step_entry["target"] = consult_department
                    step_entry["decision_rationale"] = rationale
                    step_entry["outcome"] = {
                        "consult_department": consult_department,
                        "opinion": opinion,
                        "updated_routing_candidates": list(rerouted_analysis.get("routing_candidates", []) or []),
                        "updated_chosen_department": str(rerouted_analysis.get("chosen_department", "")).strip(),
                        "what_if_override_applied": True,
                    }
                    step_entry["time"] = time_result
                    self._record_step_and_emit(state, transcript, step_entry)
                    continue
                transcript.append({"role": "er_routing_analysis", "content": str(state.er_routing_analysis)})
                handoff_result = self.diagnostic_handoff_module.run(self.case, state.to_dict(), transcript)
                forced_handoff_department = str(self.what_if_override.get("forced_handoff_department", "")).strip()
                if forced_handoff_department:
                    handoff_result["diagnostic_service"] = forced_handoff_department
                    handoff_result["responsible_department"] = forced_handoff_department
                    handoff_analysis = handoff_result.get("diagnostic_handoff_analysis", {}) or {}
                    handoff_analysis["override_notes"] = [
                        *list(handoff_analysis.get("override_notes", []) or []),
                        f"user-selected what-if forced handoff to {forced_handoff_department}",
                    ]
                    handoff_analysis["chosen_department"] = forced_handoff_department
                    handoff_result["diagnostic_handoff_analysis"] = handoff_analysis
                state.diagnostic_service = str(handoff_result.get("diagnostic_service", "")).strip()
                state.responsible_department = str(handoff_result.get("responsible_department", "")).strip() or state.responsible_department
                state.er_working_diagnosis = str(handoff_result.get("er_working_diagnosis", "")).strip() or state.er_working_diagnosis
                state.diagnostic_handoff_rationale = str(handoff_result.get("diagnostic_handoff_rationale", "")).strip()
                state.ipass_handoff = handoff_result.get("ipass_handoff", {}) or {}
                state.department_routing_scores = {
                    str(key).strip(): float(value)
                    for key, value in (handoff_result.get("department_routing_scores", {}) or {}).items()
                    if str(key).strip()
                }
                state.department_routing_candidates = [
                    str(item).strip()
                    for item in (handoff_result.get("department_routing_candidates", []) or [])
                    if str(item).strip()
                ]
                state.diagnostic_handoff_analysis = handoff_result.get("diagnostic_handoff_analysis", {}) or {}
                try:
                    state.diagnostic_handoff_confidence = float(
                        handoff_result.get("diagnostic_handoff_confidence", state.er_confidence)
                    )
                except (TypeError, ValueError):
                    state.diagnostic_handoff_confidence = state.er_confidence
                transcript.append({"role": "diagnostic_handoff_module", "content": str(handoff_result)})
                transcript.append({"role": "diagnostic_handoff_analysis", "content": str(state.diagnostic_handoff_analysis)})
                time_result = self.time_engine.advance_time(
                    self.case,
                    state,
                    actor="er_department",
                    action="make_diagnostic_summary",
                    target=state.responsible_department,
                    rationale=rationale,
                )
                step_entry["outcome"] = handoff_result
                step_entry["time"] = time_result
                self._record_step_and_emit(state, transcript, step_entry)
                break
