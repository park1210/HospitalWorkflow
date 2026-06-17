from __future__ import annotations

from typing import Any

from app.config import settings


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


def _is_specific_diagnosis(diagnosis: str) -> bool:
    normalized = str(diagnosis).strip().lower()
    if not normalized:
        return False
    return not any(normalized.startswith(prefix) for prefix in GENERIC_DIAGNOSIS_PREFIXES)


class WhatIfJudgeAgent:
    def judge_er_next_step(
        self,
        state_dict: dict[str, Any],
        routing_analysis: dict[str, Any],
        candidates: list[dict[str, str]],
    ) -> dict[str, Any]:
        scored: list[dict[str, Any]] = []
        working_diagnosis = str(routing_analysis.get("working_diagnosis", "")).strip()
        routing_scores = dict(routing_analysis.get("final_scores", {}) or {})
        top_scores = list(routing_scores.values())[:2]
        routing_margin = (top_scores[0] - top_scores[1]) if len(top_scores) >= 2 else (top_scores[0] if top_scores else 0.0)
        objective_count = len(list(state_dict.get("objective_findings", []) or []))
        patient_turns = sum(
            1
            for item in state_dict.get("decision_history", []) or []
            if str(item.get("action", "")).strip() == "ask_patient"
        )
        requested_tests = {str(item).strip() for item in state_dict.get("requested_tests", []) if str(item).strip()}
        recommended_tests = [str(item).strip() for item in state_dict.get("recommended_tests", []) if str(item).strip()]

        for candidate in candidates:
            action_type = str(candidate.get("type", "")).strip()
            target = str(candidate.get("target", "")).strip()
            score = 0.0
            reasons: list[str] = []

            if action_type == "ask_patient":
                if objective_count == 0:
                    score += 2.5
                    reasons.append("objective evidence is still sparse")
                else:
                    score -= 1.5
                    reasons.append("objective evidence already exists")
                if patient_turns >= 2:
                    score -= 1.0
                    reasons.append("ER already asked focused questions")

            elif action_type == "request_test":
                if target and target not in requested_tests and target in recommended_tests:
                    score += 2.5
                    reasons.append("recommended objective test remains pending")
                if objective_count == 0:
                    score += 1.0
                    reasons.append("objective confirmation is still needed")
                if _is_specific_diagnosis(working_diagnosis):
                    score -= 1.0
                    reasons.append("working diagnosis is already specific")

            elif action_type == "make_diagnostic_summary":
                if _is_specific_diagnosis(working_diagnosis) and objective_count >= 2:
                    score += 3.0
                    reasons.append("specific diagnosis already has objective support")
                if objective_count == 0:
                    score -= 2.0
                    reasons.append("handoff would be early without objective data")
                if routing_margin >= settings.WHAT_IF_ROUTING_MARGIN_THRESHOLD:
                    score += 1.0
                    reasons.append("routing signal is already decisive")

            scored.append(
                {
                    "action": {"type": action_type, "target": target},
                    "score": round(score, 3),
                    "reasons": reasons,
                }
            )

        ranked = sorted(scored, key=lambda item: item["score"], reverse=True)
        selected = ranked[0]["action"] if ranked else {}
        rationale = "; ".join(ranked[0]["reasons"]) if ranked and ranked[0]["reasons"] else "no strong shadow preference"
        return {
            "node": "er_next_step",
            "scored_actions": ranked,
            "selected_action": selected,
            "selection_rationale": rationale,
        }

    def judge_er_routing(
        self,
        state_dict: dict[str, Any],
        routing_analysis: dict[str, Any],
        candidates: list[dict[str, str]],
    ) -> dict[str, Any]:
        scores = {
            str(key).strip(): float(value)
            for key, value in (routing_analysis.get("final_scores_raw", {}) or {}).items()
            if str(key).strip()
        }
        exact_scores = {
            str(key).strip(): float(value)
            for key, value in (routing_analysis.get("exact_department_score_breakdown", {}) or {}).items()
            if str(key).strip()
        }
        family_scores = {
            str(key).strip(): float(value)
            for key, value in (routing_analysis.get("family_department_score_breakdown", {}) or {}).items()
            if str(key).strip()
        }
        objective_count = len(list(state_dict.get("objective_findings", []) or []))
        ranked_scores = sorted(scores.values(), reverse=True)
        margin = (ranked_scores[0] - ranked_scores[1]) if len(ranked_scores) >= 2 else (ranked_scores[0] if ranked_scores else 0.0)

        requested_tests = {str(item).strip() for item in state_dict.get("requested_tests", []) if str(item).strip()}
        recommended_tests = [str(item).strip() for item in state_dict.get("recommended_tests", []) if str(item).strip()]

        scored: list[dict[str, Any]] = []
        for candidate in candidates:
            action_type = str(candidate.get("type", "")).strip()
            target = str(candidate.get("target", "")).strip()
            score = 0.0
            reasons: list[str] = []

            if action_type == "handoff_department":
                score += scores.get(target, 0.0)
                score += exact_scores.get(target, 0.0) * 0.5
                score += family_scores.get(target, 0.0) * 0.35
                if objective_count >= 2:
                    score += 0.5
                    reasons.append("handoff can leverage existing objective evidence")
                if exact_scores.get(target, 0.0) > 0:
                    reasons.append("exact ownership evidence supports this department")
                if family_scores.get(target, 0.0) > 0:
                    reasons.append("family-level pattern supports this department")

            elif action_type == "request_test_before_handoff":
                if margin < settings.WHAT_IF_ROUTING_MARGIN_THRESHOLD:
                    score += 3.0
                    reasons.append("routing margin is still narrow")
                if objective_count < 2:
                    score += 1.5
                    reasons.append("objective evidence is still limited")
                if target and target not in requested_tests and target in recommended_tests:
                    score += 1.5
                    reasons.append("a recommended test remains uncollected")

            elif action_type == "consult_before_handoff":
                score += scores.get(target, 0.0) * 0.5
                score += family_scores.get(target, 0.0) * 0.25
                if margin < settings.WHAT_IF_ROUTING_MARGIN_THRESHOLD:
                    score += 2.0
                    reasons.append("routing margin is still narrow enough to justify a cross-specialty check")
                if objective_count >= 1:
                    score += 1.0
                    reasons.append("there is enough evidence for a specialty opinion to be informative")
                reasons.append("consult-first can test the alternative department without forcing a reroute")

            scored.append(
                {
                    "action": {"type": action_type, "target": target},
                    "score": round(score, 3),
                    "reasons": reasons,
                }
            )

        ranked = sorted(scored, key=lambda item: item["score"], reverse=True)
        selected = ranked[0]["action"] if ranked else {}
        rationale = "; ".join(ranked[0]["reasons"]) if ranked and ranked[0]["reasons"] else "no strong shadow preference"
        return {
            "node": "er_routing",
            "scored_actions": ranked,
            "selected_action": selected,
            "selection_rationale": rationale,
        }
