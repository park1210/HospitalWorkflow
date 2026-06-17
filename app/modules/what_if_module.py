from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.agents.what_if_judge_agent import WhatIfJudgeAgent
from app.config import settings
from app.utils.action_candidates import (
    build_er_next_step_candidates,
    build_er_routing_candidates,
    build_specialty_finalize_candidates,
    build_specialty_next_step_candidates,
)


class WhatIfModule:
    def __init__(self) -> None:
        self.judge = WhatIfJudgeAgent()

    def _build_snapshot_base(
        self,
        *,
        case_id: str,
        turn_index: int,
        node: str,
        state_dict: dict[str, Any],
        transcript: list[dict[str, str]],
        proposed_action: dict[str, Any],
        alternatives: list[dict[str, str]],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot_id = f"{case_id}_turn_{turn_index}_{node}"
        return {
            "snapshot_id": snapshot_id,
            "case_id": str(case_id).strip(),
            "turn_index": int(turn_index),
            "node": str(node).strip(),
            "state_snapshot": deepcopy(state_dict),
            "transcript_snapshot": deepcopy(transcript),
            "proposed_action": deepcopy(proposed_action),
            "alternatives": deepcopy(alternatives),
            "metadata": deepcopy(metadata),
        }

    def build_er_next_step_snapshot(
        self,
        *,
        state_dict: dict[str, Any],
        transcript: list[dict[str, str]],
        proposed_action: str,
        proposed_target: str,
        proposed_rationale: str,
        turn_index: int,
        case_id: str,
    ) -> dict[str, Any]:
        candidates = build_er_next_step_candidates(state_dict, proposed_action, proposed_target)
        metadata = {
            "working_diagnosis": str(state_dict.get("er_working_diagnosis", "")).strip(),
            "objective_findings_count": len(list(state_dict.get("objective_findings", []) or [])),
            "requested_tests": list(state_dict.get("requested_tests", []) or []),
            "recommended_tests": list(state_dict.get("recommended_tests", []) or []),
        }
        return self._build_snapshot_base(
            case_id=case_id,
            turn_index=turn_index,
            node="er_next_step",
            state_dict=state_dict,
            transcript=transcript,
            proposed_action={
                "type": str(proposed_action).strip(),
                "target": str(proposed_target).strip(),
                "rationale": str(proposed_rationale).strip(),
            },
            alternatives=candidates,
            metadata=metadata,
        )

    def build_er_routing_snapshot(
        self,
        *,
        state_dict: dict[str, Any],
        transcript: list[dict[str, str]],
        routing_analysis: dict[str, Any],
        turn_index: int,
        case_id: str,
    ) -> dict[str, Any]:
        candidates = build_er_routing_candidates(state_dict, routing_analysis)
        chosen_department = str(routing_analysis.get("chosen_department", "")).strip()
        metadata = {
            "working_diagnosis": str(routing_analysis.get("working_diagnosis", "")).strip(),
            "routing_candidates": list(routing_analysis.get("routing_candidates", []) or []),
            "routing_scores": dict(routing_analysis.get("final_scores", {}) or {}),
            "objective_findings_count": len(list(state_dict.get("objective_findings", []) or [])),
        }
        return self._build_snapshot_base(
            case_id=case_id,
            turn_index=turn_index,
            node="er_routing",
            state_dict=state_dict,
            transcript=transcript,
            proposed_action={
                "type": "handoff_department",
                "target": chosen_department,
                "rationale": str(routing_analysis.get("rationale", "")).strip(),
            },
            alternatives=candidates,
            metadata=metadata,
        )

    def build_specialty_finalize_snapshot(
        self,
        *,
        state_dict: dict[str, Any],
        transcript: list[dict[str, str]],
        department: str,
        refined_diagnosis: str,
        proposed_action: str,
        proposed_target: str,
        proposed_rationale: str,
        turn_index: int,
        case_id: str,
        next_test: str = "",
        llm_candidate_diagnoses: list[str] | None = None,
    ) -> dict[str, Any]:
        candidates = build_specialty_finalize_candidates(
            state_dict,
            proposed_action=proposed_action,
            proposed_target=proposed_target,
            refined_diagnosis=refined_diagnosis,
            next_test=next_test,
            llm_candidate_diagnoses=llm_candidate_diagnoses,
        )
        metadata = {
            "department": str(department).strip(),
            "working_diagnosis": str(state_dict.get("er_working_diagnosis", "")).strip(),
            "refined_diagnosis": str(refined_diagnosis).strip(),
            "objective_findings_count": len(list(state_dict.get("objective_findings", []) or [])),
            "requested_tests": list(state_dict.get("requested_tests", []) or []),
            "llm_candidate_diagnoses": list(llm_candidate_diagnoses or []),
            "suggested_next_test": str(next_test).strip(),
        }
        return self._build_snapshot_base(
            case_id=case_id,
            turn_index=turn_index,
            node="specialty_finalize",
            state_dict=state_dict,
            transcript=transcript,
            proposed_action={
                "type": str(proposed_action).strip(),
                "target": str(proposed_target).strip(),
                "rationale": str(proposed_rationale).strip(),
            },
            alternatives=candidates,
            metadata=metadata,
        )

    def build_specialty_next_step_snapshot(
        self,
        *,
        state_dict: dict[str, Any],
        transcript: list[dict[str, str]],
        department: str,
        working_diagnosis: str,
        proposed_action: str,
        proposed_target: str,
        proposed_rationale: str,
        turn_index: int,
        case_id: str,
        next_test: str = "",
        can_ask_patient: bool = False,
    ) -> dict[str, Any]:
        candidates = build_specialty_next_step_candidates(
            proposed_action=proposed_action,
            proposed_target=proposed_target,
            can_ask_patient=can_ask_patient,
            next_test=next_test,
        )
        metadata = {
            "department": str(department).strip(),
            "working_diagnosis": str(working_diagnosis).strip(),
            "objective_findings_count": len(list(state_dict.get("objective_findings", []) or [])),
            "requested_tests": list(state_dict.get("requested_tests", []) or []),
            "can_ask_patient": bool(can_ask_patient),
            "suggested_next_test": str(next_test).strip(),
        }
        return self._build_snapshot_base(
            case_id=case_id,
            turn_index=turn_index,
            node="specialty_next_step",
            state_dict=state_dict,
            transcript=transcript,
            proposed_action={
                "type": str(proposed_action).strip(),
                "target": str(proposed_target).strip(),
                "rationale": str(proposed_rationale).strip(),
            },
            alternatives=candidates,
            metadata=metadata,
        )

    def evaluate_er_next_step_shadow(
        self,
        state_dict: dict[str, Any],
        routing_analysis: dict[str, Any],
        proposed_action: str,
        proposed_target: str,
        proposed_rationale: str,
    ) -> dict[str, Any]:
        candidates = build_er_next_step_candidates(state_dict, proposed_action, proposed_target)
        judged = self.judge.judge_er_next_step(state_dict, routing_analysis, candidates)
        return {
            "mode": "shadow",
            "node": "er_next_step",
            "proposed_action": {
                "type": str(proposed_action).strip(),
                "target": str(proposed_target).strip(),
                "rationale": str(proposed_rationale).strip(),
            },
            "alternatives": candidates,
            "selected_action": judged.get("selected_action", {}),
            "selection_rationale": judged.get("selection_rationale", ""),
            "scored_actions": judged.get("scored_actions", []),
            "applied": False,
        }

    def evaluate_er_routing_shadow(
        self,
        state_dict: dict[str, Any],
        routing_analysis: dict[str, Any],
    ) -> dict[str, Any]:
        candidates = build_er_routing_candidates(state_dict, routing_analysis)
        judged = self.judge.judge_er_routing(state_dict, routing_analysis, candidates)
        chosen_department = str(routing_analysis.get("chosen_department", "")).strip()
        return {
            "mode": "shadow",
            "node": "er_routing",
            "proposed_action": {
                "type": "handoff_department",
                "target": chosen_department,
                "rationale": str(routing_analysis.get("rationale", "")).strip(),
            },
            "alternatives": candidates,
            "selected_action": judged.get("selected_action", {}),
            "selection_rationale": judged.get("selection_rationale", ""),
            "scored_actions": judged.get("scored_actions", []),
            "applied": False,
        }
