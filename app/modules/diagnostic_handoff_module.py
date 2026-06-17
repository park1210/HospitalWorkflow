from __future__ import annotations

from typing import Any

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
from app.utils.diagnosis_catalog import extract_known_diagnoses, has_direct_diagnosis_support, match_known_diagnosis
from app.utils.ownership_rules import apply_department_ownership_overrides


GENERIC_DIAGNOSIS_PREFIXES = (
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


class DiagnosticHandoffModule:
    ROUTING_REVIEW_GAP = 1.0
    ROUTING_FALLBACK_GAP = 1.5

    def _compact_score_map(self, score_map: dict[str, float], limit: int = 5) -> dict[str, float]:
        return {
            department: round(float(score), 3)
            for department, score in rank_department_scores(score_map)[:limit]
            if float(score) > 0
        }

    def _apply_objective_ownership_overrides(
        self,
        department_scores: dict[str, float],
        objective_findings: list[Any],
        known_information: list[Any],
    ) -> tuple[dict[str, float], list[str]]:
        evidence_text = " ".join(
            str(item).strip().lower()
            for item in [*objective_findings, *known_information]
            if str(item).strip()
        )
        return apply_department_ownership_overrides(department_scores, evidence_text)

    def _build_department_scores(
        self,
        state: dict[str, Any],
        working_diagnosis: str,
        objective_findings: list[Any],
        consult_history: list[Any],
    ) -> tuple[
        dict[str, float],
        dict[str, dict[str, float]],
        dict[str, float],
        dict[str, float],
        list[str],
        dict[str, Any],
    ]:
        consult_opinions = [
            str(item.get("opinion", "")).strip()
            for item in consult_history
            if isinstance(item, dict) and str(item.get("opinion", "")).strip()
        ]
        source_payload = {
            "working_diagnosis": working_diagnosis,
            "objective_findings": [str(item).strip() for item in objective_findings if str(item).strip()],
            "chief_complaint": str(state.get("arrival_info", "")).strip(),
            "history": " ".join(
                str(item).strip()
                for item in state.get("known_information", [])[-6:]
                if str(item).strip()
            ),
            "consult_opinions": consult_opinions,
            "working_problem_list": [str(item).strip() for item in state.get("working_problem_list", []) if str(item).strip()],
            "known_information": [str(item).strip() for item in state.get("known_information", [])[-4:] if str(item).strip()],
            "assessment_signals": [f"{dept} {score}" for dept, score in (state.get("candidate_scores", {}) or {}).items()],
        }
        source_score_breakdown: dict[str, dict[str, float]] = {}
        for source_name, raw_value in source_payload.items():
            source_scores = infer_department_scores_by_source({source_name: raw_value}, prefer_clinical_department=True)
            compact = self._compact_score_map(source_scores)
            if compact:
                source_score_breakdown[source_name] = compact

        weighted_scores = infer_department_scores_by_source(source_payload, prefer_clinical_department=True)
        assessment_scores = {
            str(key).strip(): float(value)
            for key, value in (state.get("candidate_scores", {}) or {}).items()
            if str(key).strip()
        }
        structured_profile = build_structured_evidence_profile(
            working_diagnosis=working_diagnosis,
            chief_complaint=str(state.get("arrival_info", "")).strip(),
            history=" ".join(
                str(item).strip()
                for item in state.get("known_information", [])[-6:]
                if str(item).strip()
            ),
            objective_findings=objective_findings,
            known_information=state.get("known_information", [])[-6:] if isinstance(state.get("known_information", []), list) else [],
            assessment_family_scores={
                str(key).strip(): float(value)
                for key, value in (state.get("family_signal_scores", {}) or {}).items()
                if str(key).strip()
            },
        )
        catalog_query = " ".join(
            [
                working_diagnosis,
                " ".join(str(item).strip() for item in objective_findings if str(item).strip()),
                " ".join(str(item).strip() for item in state.get("known_information", [])[-3:] if str(item).strip()),
            ]
        ).strip()
        catalog_scores = infer_department_scores_from_catalog(catalog_query, limit=6, min_score=0.34)
        combined_scores = combine_department_scores(
            weighted_scores,
            assessment_scores,
            catalog_scores,
            dict(structured_profile.get("exact_department_scores", {}) or {}),
            dict(structured_profile.get("family_department_scores", {}) or {}),
        )
        combined_scores, override_notes = self._apply_objective_ownership_overrides(
            combined_scores,
            objective_findings,
            state.get("known_information", [])[-4:] if isinstance(state.get("known_information", []), list) else [],
        )
        return combined_scores, source_score_breakdown, assessment_scores, catalog_scores, override_notes, structured_profile

    def _compact_text(self, text: str, limit: int = 180) -> str:
        value = " ".join(str(text).strip().split())
        if len(value) <= limit:
            return value
        return value[: limit - 3].rstrip() + "..."

    def _build_ipass_handoff(
        self,
        state: dict[str, Any],
        responsible_department: str,
        working_diagnosis: str,
        handoff_rationale: str,
        confidence: float,
    ) -> dict[str, Any]:
        objective_findings = [str(item).strip() for item in state.get("objective_findings", []) if str(item).strip()]
        known_tail = [str(item).strip() for item in state.get("known_information", [])[-4:] if str(item).strip()]
        working_problem_list = [str(item).strip() for item in state.get("working_problem_list", [])[:3] if str(item).strip()]
        top_findings = objective_findings[-3:]

        if confidence >= 0.85 and self._is_specific_diagnosis(working_diagnosis):
            illness_severity = "stable-resolved-in-er"
        elif confidence >= 0.6:
            illness_severity = "stable-but-unresolved"
        else:
            illness_severity = "watcher"

        chief_context = self._compact_text(str(state.get("arrival_info", "")).strip(), limit=140)
        patient_summary_parts = [
            chief_context,
            f"ER diagnosis: {working_diagnosis}" if working_diagnosis else "",
            f"Target: {responsible_department}" if responsible_department else "",
        ]
        patient_summary = " | ".join(part for part in patient_summary_parts if part)

        action_list = [
            f"Review ER objective findings for {responsible_department} relevance.",
            "Decide whether one focused specialty question or one focused additional test is still needed.",
            "If evidence is sufficient, finalize the specialty diagnosis directly.",
        ]

        situation_awareness = [
            *top_findings,
            *working_problem_list,
            *known_tail[-2:],
        ][:5]

        receiver_synthesis_target = (
            f"Confirm or revise the ER working diagnosis '{working_diagnosis or 'undifferentiated acute complaint'}' "
            f"using only the handoff summary and the most relevant specialty evidence."
        )

        return {
            "illness_severity": illness_severity,
            "patient_summary": patient_summary,
            "action_list": action_list,
            "situation_awareness": situation_awareness,
            "receiver_synthesis_target": receiver_synthesis_target,
            "handoff_rationale": handoff_rationale,
        }

    def _is_specific_diagnosis(self, diagnosis: str) -> bool:
        normalized = str(diagnosis).strip().lower()
        if not normalized:
            return False
        return not any(normalized.startswith(prefix) for prefix in GENERIC_DIAGNOSIS_PREFIXES)

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

    def _review_department_choice(
        self,
        *,
        working_diagnosis: str,
        objective_findings: list[Any],
        department_scores: dict[str, float],
        source_score_breakdown: dict[str, dict[str, float]],
        structured_profile: dict[str, Any],
        initially_chosen_department: str,
    ) -> tuple[str, dict[str, Any]]:
        ranked = rank_department_scores(department_scores)
        normalized_initial = normalize_department(initially_chosen_department, default="general_medicine")
        top_candidates = build_department_candidates(department_scores, limit=2)
        generic_working_diagnosis = not self._is_specific_diagnosis(working_diagnosis)
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
        exact_scores = dict(structured_profile.get("exact_department_scores", {}) or {})
        top1_exact = float(exact_scores.get(top1_department, 0.0) or 0.0)
        top2_exact = float(exact_scores.get(top2_department, 0.0) or 0.0)
        review["ownership_signals"] = {
            top1_department: top1_ownership,
            top2_department: top2_ownership,
        }
        review["exact_department_scores"] = {
            top1_department: round(top1_exact, 4),
            top2_department: round(top2_exact, 4),
        }

        if (
            generic_working_diagnosis
            and objective_count >= 2
            and score_margin < self.ROUTING_REVIEW_GAP
            and top2_ownership > (top1_ownership + 0.25)
            and (
                normalized_initial in GENERAL_FALLBACK_DEPARTMENTS
                or top2_exact > (top1_exact + 0.5)
            )
        ):
            review["review_applied"] = True
            review["review_reason"] = (
                f"routing review favored {top2_department} because the ER handoff stayed generic, "
                "the alternative specialty ownership signal was stronger, and the alternative had stronger exact specialty support."
            )
            return top2_department, review

        if (
            normalized_initial in GENERAL_FALLBACK_DEPARTMENTS
            and score_margin < self.ROUTING_FALLBACK_GAP
            and top2_ownership >= top1_ownership
        ):
            review["review_applied"] = True
            review["review_reason"] = (
                f"routing review replaced fallback routing with {top2_department} because the specific specialty "
                "alternative had at least comparable ownership support."
            )
            return top2_department, review

        return normalized_initial, review

    def _extract_supported_diagnosis(self, texts: list[str]) -> str:
        cleaned = [str(item).strip() for item in texts if str(item).strip()]
        if not cleaned:
            return ""

        combined_text = "\n".join(cleaned)
        extracted = extract_known_diagnoses(combined_text, limit=1)
        if extracted and has_direct_diagnosis_support(combined_text, extracted[0]):
            return extracted[0]

        for text in cleaned:
            matched = match_known_diagnosis(text)
            if matched:
                return matched

        return ""

    def run(self, case: dict[str, Any], state: dict[str, Any], transcript: list[dict[str, str]]) -> dict[str, Any]:
        fallback_department = normalize_department(
            state.get("responsible_department") or state.get("final_department") or "general_medicine",
            default="general_medicine",
        )
        working_diagnosis = str(state.get("er_working_diagnosis") or state.get("final_diagnosis") or "").strip()
        confidence = float(state.get("er_confidence", 0.0) or 0.0)
        consult_history = state.get("consultation_history", []) or []
        objective_findings = state.get("objective_findings", []) or []
        consult_opinions = [
            str(item.get("opinion", "")).strip()
            for item in consult_history
            if isinstance(item, dict) and str(item.get("opinion", "")).strip()
        ]

        supported_diagnosis = self._extract_supported_diagnosis(
            [
                *objective_findings,
                *consult_opinions,
                str(state.get("arrival_info", "")).strip(),
            ]
        )
        if supported_diagnosis and not self._is_specific_diagnosis(working_diagnosis):
            working_diagnosis = supported_diagnosis

        if not working_diagnosis:
            working_problem_list = [str(item).strip() for item in state.get("working_problem_list", []) if str(item).strip()]
            if working_problem_list:
                working_diagnosis = working_problem_list[0]

        department_scores, source_score_breakdown, assessment_scores, catalog_scores, override_notes, structured_profile = self._build_department_scores(
            state, working_diagnosis, objective_findings, consult_history
        )
        er_routing_review = dict((state.get("er_routing_analysis", {}) or {}).get("routing_review", {}) or {})
        if bool(er_routing_review.get("review_applied")) and fallback_department:
            department_scores[fallback_department] = max(
                float(department_scores.get(fallback_department, 0.0) or 0.0),
                float(department_scores.get(fallback_department, 0.0) or 0.0) + 2.0,
            )
            override_notes.append(
                f"handoff preserved ER routing review preference for {fallback_department}"
            )
        inferred_department = choose_department_from_scores(
            department_scores,
            default=fallback_department,
            fallback_if_ambiguous="internal_medicine",
            ambiguity_margin=1.5,
            low_confidence_threshold=1.5,
        )
        inferred_department = prefer_specific_department(department_scores, inferred_department)
        responsible_department = normalize_department(inferred_department or fallback_department, default="general_medicine")
        responsible_department, routing_review = self._review_department_choice(
            working_diagnosis=working_diagnosis,
            objective_findings=objective_findings,
            department_scores=department_scores,
            source_score_breakdown=source_score_breakdown,
            structured_profile=structured_profile,
            initially_chosen_department=responsible_department,
        )

        consult_departments = {
            str(item.get("department", "")).strip()
            for item in consult_history
            if isinstance(item, dict) and str(item.get("department", "")).strip()
        }
        consult_departments.discard("")

        if responsible_department in {"general_medicine", "internal_medicine", "radiology"} and len(consult_departments) == 1:
            responsible_department = normalize_department(next(iter(consult_departments)), default=responsible_department)

        if supported_diagnosis and objective_findings:
            handoff_rationale = "The ER gathered objective evidence that now supports a specific diagnostic handoff to the aligned specialty service."
        elif responsible_department in consult_departments:
            handoff_rationale = "The ER gathered objective evidence and specialty input, so the case is ready for department-level diagnostic refinement."
        elif objective_findings:
            handoff_rationale = "The ER gathered objective evidence and can now hand the case to the most likely diagnostic department."
        else:
            handoff_rationale = "The ER completed its initial diagnostic workup and prepared a structured working diagnosis for specialty review."

        ranked_scores = rank_department_scores(department_scores)
        score_margin = 0.0
        if len(ranked_scores) > 1:
            score_margin = float(ranked_scores[0][1]) - float(ranked_scores[1][1])

        if supported_diagnosis and len(objective_findings) >= 2 and score_margin >= 1.5:
            handoff_confidence = max(confidence, 0.9)
        elif supported_diagnosis and objective_findings:
            handoff_confidence = max(confidence, 0.75)
        elif objective_findings:
            handoff_confidence = max(confidence, 0.6)
        else:
            handoff_confidence = confidence
        ipass_handoff = self._build_ipass_handoff(
            state,
            responsible_department,
            working_diagnosis,
            handoff_rationale,
            handoff_confidence,
        )
        top_evidence = [
            *[str(item).strip() for item in objective_findings[:3] if str(item).strip()],
            *[str(item).strip() for item in state.get("known_information", [])[-2:] if str(item).strip()],
        ][:4]
        routing_candidates = build_department_candidates(department_scores, limit=2)
        top_sources = [name for name, values in source_score_breakdown.items() if responsible_department in values][:2]
        rationale_bits = []
        if top_sources:
            rationale_bits.append(f"{responsible_department} was mainly supported by {', '.join(top_sources)}")
        if override_notes:
            rationale_bits.append(f"override applied: {override_notes[0]}")
        if routing_candidates:
            rationale_bits.append(f"top shortlist: {routing_candidates}")
        if routing_review.get("review_applied"):
            rationale_bits.append(str(routing_review.get("review_reason", "")).strip())

        return {
            "diagnostic_service": responsible_department,
            "responsible_department": responsible_department,
            "er_working_diagnosis": working_diagnosis,
            "diagnostic_handoff_rationale": handoff_rationale,
            "diagnostic_handoff_confidence": handoff_confidence,
            "department_routing_candidates": routing_candidates,
            "department_routing_scores": {
                department: round(score, 3)
                for department, score in rank_department_scores(department_scores)[:5]
            },
            "diagnostic_handoff_analysis": {
                "supported_diagnosis": supported_diagnosis,
                "dominant_family": str(structured_profile.get("dominant_family", "")).strip(),
                "family_score_breakdown": self._compact_score_map(dict(structured_profile.get("family_scores", {}) or {})),
                "family_department_score_breakdown": self._compact_score_map(
                    dict(structured_profile.get("family_department_scores", {}) or {})
                ),
                "exact_diagnosis_hits": list(structured_profile.get("exact_diagnosis_hits", []) or []),
                "exact_department_score_breakdown": self._compact_score_map(
                    dict(structured_profile.get("exact_department_scores", {}) or {})
                ),
                "top_evidence": top_evidence,
                "source_score_breakdown": source_score_breakdown,
                "assessment_score_breakdown": self._compact_score_map(assessment_scores),
                "catalog_score_breakdown": self._compact_score_map(catalog_scores),
                "final_scores": self._compact_score_map(department_scores),
                "routing_candidates": routing_candidates,
                "routing_review": routing_review,
                "chosen_department": responsible_department,
                "override_notes": override_notes,
                "rationale": ". ".join(rationale_bits).strip(),
            },
            "ipass_handoff": ipass_handoff,
        }
