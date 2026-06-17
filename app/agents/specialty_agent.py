import json
import re
from typing import Any, Optional

from app.config import settings
from app.llm.ollama_client import OllamaClient
from app.modules.what_if_module import WhatIfModule
from app.utils.department_catalog import get_curated_department_assignment, infer_department_scores_by_source, normalize_department, rank_department_scores
from app.utils.diagnosis_catalog import canonicalize_diagnosis_text, extract_known_diagnoses, has_direct_diagnosis_support, infer_catalog_diagnosis_from_evidence, match_known_diagnosis, search_known_diagnoses
from app.utils.prompt_loader import load_prompt
from app.utils.specialty_department_policy import (
    get_specialty_diagnostic_focus,
    get_specialty_generic_fallback_rules,
    get_specialty_interview_question,
    get_specialty_next_step_prompt,
    get_specialty_test_priorities,
    specialty_matches_keywords,
)


DEFAULT_SPECIALTY_SYSTEM_FALLBACK = (
    "You are the receiving specialty department in a hospital diagnostic workflow. "
    "Use only the provided ER handoff and objective evidence. "
    "Return a concise specialty diagnosis and a short diagnostic plan."
)

DEFAULT_DEPARTMENT_PROMPT_FALLBACK = (
    "Use the lens of the receiving specialty department. "
    "Prioritize objective evidence, avoid unsupported specificity, and answer concisely."
)

GENERIC_DIAGNOSIS_PREFIXES = (
    "possible ",
    "undifferentiated",
    "acute abdominal",
    "acute ",
)

class DepartmentDiagnosticAgent:
    def __init__(self, department: str) -> None:
        self.department = normalize_department(department, default="general_medicine")
        self.client = OllamaClient(
            base_url=settings.SPECIALTY_BASE_URL,
            api_key=settings.SPECIALTY_API_KEY,
        )
        self.what_if_module = WhatIfModule()
        self.system_prompt = load_prompt(
            "specialty_department_system.txt",
            DEFAULT_SPECIALTY_SYSTEM_FALLBACK,
        )
        self.department_prompt = load_prompt(
            f"specialty/{self.department}.txt",
            DEFAULT_DEPARTMENT_PROMPT_FALLBACK,
        )

    def _combined_text(self, state: dict[str, Any], transcript: list[dict[str, str]]) -> str:
        transcript_text = " ".join(str(entry.get("content", "")) for entry in transcript)
        state_text = " ".join(str(item) for item in state.get("known_information", []))
        objective_text = " ".join(str(item) for item in state.get("objective_findings", []))
        return f"{state_text} {objective_text} {transcript_text}".lower()

    def _compact_ipass_handoff(self, state: dict[str, Any]) -> dict[str, Any]:
        handoff = state.get("ipass_handoff", {}) or {}
        if not isinstance(handoff, dict):
            handoff = {}
        return {
            "illness_severity": str(handoff.get("illness_severity", "")).strip(),
            "patient_summary": str(handoff.get("patient_summary", "")).strip(),
            "action_list": [str(item).strip() for item in handoff.get("action_list", [])[:3] if str(item).strip()],
            "situation_awareness": [str(item).strip() for item in handoff.get("situation_awareness", [])[:4] if str(item).strip()],
            "receiver_synthesis_target": str(handoff.get("receiver_synthesis_target", "")).strip(),
            "handoff_rationale": str(handoff.get("handoff_rationale", "")).strip(),
        }

    def _collect_context(self, state: dict[str, Any], transcript: list[dict[str, str]]) -> tuple[str, list[str]]:
        working = str(state.get("er_working_diagnosis", "")).strip()
        objective_findings = [str(item).strip() for item in state.get("objective_findings", []) if str(item).strip()]
        if not working and objective_findings:
            extracted = extract_known_diagnoses("\n".join(objective_findings), limit=1)
            if extracted:
                working = extracted[0]
        if not working:
            suspected = [str(item).strip() for item in state.get("suspected_diagnoses", []) if str(item).strip()]
            if suspected:
                working = suspected[0]
        if not working:
            problems = [str(item).strip() for item in state.get("working_problem_list", []) if str(item).strip()]
            if problems:
                working = problems[0]
        return working or "undifferentiated acute complaint", objective_findings

    def _is_specific_diagnosis(self, diagnosis: str) -> bool:
        normalized = str(diagnosis).strip().lower()
        if not normalized:
            return False
        return not any(normalized.startswith(prefix) for prefix in GENERIC_DIAGNOSIS_PREFIXES)

    def _is_runtime_candidate_allowed(self, diagnosis: str) -> bool:
        text = str(diagnosis).strip()
        if not text:
            return False
        assignment = get_curated_department_assignment(text)
        if not assignment:
            return True
        department = normalize_department(str(assignment.get("department", "")).strip(), default="")
        return bool(department)

    def _department_evidence_text(self, state: dict[str, Any], working_diagnosis: str, objective_findings: list[str]) -> str:
        known_tail = " ".join(str(item).strip() for item in state.get("known_information", [])[-6:] if str(item).strip())
        problems = " ".join(str(item).strip() for item in state.get("working_problem_list", []) if str(item).strip())
        objective_text = " ".join(objective_findings)
        return f"{working_diagnosis} {objective_text} {known_tail} {problems}".lower()

    def _has_lower_urinary_pattern(self, text: str) -> bool:
        normalized = str(text).lower()
        lower_urinary_markers = [
            "bladder discomfort",
            "relieved by voiding",
            "cystoscopy",
            "postvoid",
            "post-void",
        ]
        normal_urine_markers = [
            "wbc': '0/hpf",
            "bacteria': 'none'",
            "nitrite': 'negative'",
            "leukocyte esterase': 'negative'",
            "blood': 'negative'",
        ]
        return any(marker in normalized for marker in lower_urinary_markers) and sum(
            1 for marker in normal_urine_markers if marker in normalized
        ) >= 2

    def _has_renal_inflammatory_pattern(self, text: str) -> bool:
        normalized = str(text).lower()
        renal_markers = [
            "eosinophil",
            "eosinophilic",
            "hansel",
            "pyuria",
            "hematuria",
            "proteinuria",
            "interstitial nephritis",
            "creatinine",
            "leukocyte esterase': 'positive'",
            "wbc': '",
        ]
        return sum(1 for marker in renal_markers if marker in normalized) >= 3

    def _has_bone_lesion_pattern(self, text: str) -> bool:
        normalized = str(text).lower()
        lesion_markers = [
            "lytic lesion",
            "soap bubble",
            "distal femur",
            "clear demarcation",
            "benign process",
            "non-invasive",
        ]
        return sum(1 for marker in lesion_markers if marker in normalized) >= 2

    def _has_degenerative_msk_label(self, diagnosis: str) -> bool:
        normalized = canonicalize_diagnosis_text(str(diagnosis).strip())
        if not normalized:
            return False
        degenerative_markers = [
            "osteoarthritis",
            "degenerative joint",
            "osteoarthrosis",
        ]
        return any(marker in normalized for marker in degenerative_markers)

    def _filter_exact_candidates_by_pattern(
        self,
        text: str,
        candidates: list[str],
    ) -> list[str]:
        filtered: list[str] = []
        normalized_text = str(text).strip()
        for diagnosis in candidates:
            label = str(diagnosis).strip()
            if not label:
                continue
            canonical = canonicalize_diagnosis_text(label)
            assignment = get_curated_department_assignment(label) or {}
            candidate_department = normalize_department(str(assignment.get("department", "")).strip(), default="")

            if (
                self._has_bone_lesion_pattern(normalized_text)
                and candidate_department == "orthopedics"
                and self._has_degenerative_msk_label(label)
                and not has_direct_diagnosis_support(normalized_text, label)
            ):
                continue

            if (
                self._has_lower_urinary_pattern(normalized_text)
                and not self._has_renal_inflammatory_pattern(normalized_text)
                and candidate_department == "nephrology"
                and not has_direct_diagnosis_support(normalized_text, label)
            ):
                continue

            filtered.append(label)
        return filtered

    def _preferred_exact_candidate_from_evidence(
        self,
        state: dict[str, Any],
        objective_findings: list[str],
        candidates: list[str],
    ) -> str:
        exact_candidates = [str(item).strip() for item in candidates if self._is_specific_diagnosis(str(item).strip())]
        if not exact_candidates:
            return ""

        objective_text = "\n".join(objective_findings)
        focused_text = " ".join(
            [
                objective_text,
                str(state.get("arrival_info", "")).strip(),
                str((state.get("ipass_handoff", {}) or {}).get("patient_summary", "")).strip(),
                self._history_rescue_query(state),
            ]
        ).strip()

        evidence_hint = infer_catalog_diagnosis_from_evidence(focused_text)
        if evidence_hint:
            hinted = canonicalize_diagnosis_text(evidence_hint)
            for candidate in exact_candidates:
                if canonicalize_diagnosis_text(candidate) == hinted:
                    return candidate

        if self._has_lower_urinary_pattern(focused_text) and not self._has_renal_inflammatory_pattern(focused_text):
            for candidate in exact_candidates:
                assignment = get_curated_department_assignment(candidate) or {}
                candidate_department = normalize_department(str(assignment.get("department", "")).strip(), default="")
                if candidate_department == self.department and has_direct_diagnosis_support(focused_text, candidate):
                    return candidate

        if self._has_bone_lesion_pattern(focused_text):
            for candidate in exact_candidates:
                assignment = get_curated_department_assignment(candidate) or {}
                candidate_department = normalize_department(str(assignment.get("department", "")).strip(), default="")
                if (
                    candidate_department == self.department
                    and not self._has_degenerative_msk_label(candidate)
                    and has_direct_diagnosis_support(focused_text, candidate)
                ):
                    return candidate

        return ""

    def _requires_direct_support_for_exact_candidate(self, diagnosis: str) -> bool:
        return False

    def _sanitize_history_fragment(self, text: str) -> str:
        cleaned = str(text).strip()
        if not cleaned:
            return ""
        cleaned = re.sub(r"\bI have a history of\b.*?(?:\.|$)", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bhas a history of\b.*?(?:\.|$)", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bfamily history\b.*?(?:\.|$)", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bpast medical history\b.*?(?:\.|$)", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _history_rescue_query(self, state: dict[str, Any]) -> str:
        history_fragments: list[str] = []
        for item in state.get("known_information", []) or []:
            text = str(item).strip()
            lowered = text.lower()
            if not text:
                continue
            if "consult:" in lowered or "triage level" in lowered or "assessment completed" in lowered:
                continue
            if lowered.startswith("blood_") or lowered.startswith("routine_") or lowered.startswith("imaging:") or lowered.startswith("biopsy:"):
                continue
            if "{" in text or "}" in text:
                continue
            cleaned = self._sanitize_history_fragment(text)
            if cleaned:
                history_fragments.append(cleaned)

        return " ".join(
            [
                str(state.get("arrival_info", "")).strip(),
                " ".join(history_fragments[-4:]),
                str((state.get("ipass_handoff", {}) or {}).get("patient_summary", "")).strip(),
            ]
        ).strip()

    def _available_section_names(self, test_module: Any) -> list[str]:
        hidden_tests = getattr(test_module, "hidden_test_results", {}) or {}
        hidden_exams = getattr(test_module, "hidden_exam_results", {}) or {}
        section_names = [str(name).strip() for name in list(hidden_tests.keys()) + list(hidden_exams.keys()) if str(name).strip()]
        seen: set[str] = set()
        ordered: list[str] = []
        for name in section_names:
            lowered = name.lower()
            if lowered not in seen:
                seen.add(lowered)
                ordered.append(name)
        return ordered

    def _choose_additional_test(self, state: dict[str, Any], test_module: Any) -> str:
        if test_module is None:
            return ""

        requested = {
            str(item).strip().lower()
            for item in [
                *(state.get("requested_tests", []) or []),
                *(state.get("requested_exams", []) or []),
            ]
            if str(item).strip()
        }
        available_sections = self._available_section_names(test_module)
        priorities = get_specialty_test_priorities(self.department)
        for priority in priorities:
            normalized_priority = priority.lower()
            for section_name in available_sections:
                normalized_section = section_name.lower()
                if normalized_section in requested:
                    continue
                if normalized_priority in normalized_section:
                    return section_name
        return ""

    def _choose_interview_question(self, state: dict[str, Any]) -> str:
        default_question = "Has anything changed about the symptoms or history that seems important now?"
        return get_specialty_interview_question(self.department, default_question)

    def _append_local_known_information(self, state: dict[str, Any], text: str) -> None:
        value = str(text).strip()
        if value and value not in state["known_information"]:
            state["known_information"].append(value)

    def _matches_what_if_override(
        self,
        what_if_override: Optional[dict[str, Any]],
        *,
        node: str,
        turn_index: int,
    ) -> bool:
        if not what_if_override or what_if_override.get("consumed"):
            return False
        return (
            str(what_if_override.get("node", "")).strip() == str(node).strip()
            and int(what_if_override.get("turn_index", -1) or -1) == int(turn_index)
        )

    def _specialty_support_text(
        self,
        state: dict[str, Any],
        objective_findings: list[str],
        diagnosis: str,
    ) -> str:
        return " ".join(
            [
                "\n".join(objective_findings),
                str(state.get("arrival_info", "")).strip(),
                str((state.get("ipass_handoff", {}) or {}).get("patient_summary", "")).strip(),
                self._history_rescue_query(state),
                str(diagnosis).strip(),
            ]
        ).strip()

    def _best_committable_specialty_diagnosis(
        self,
        *,
        state: dict[str, Any],
        refined_diagnosis: str,
        deterministic_candidate: str,
        objective_findings: list[str],
        llm_candidate_diagnoses: list[str],
    ) -> str:
        support_text = self._specialty_support_text(state, objective_findings, refined_diagnosis)
        objective_count = len(objective_findings)
        preferred_exact = self._preferred_exact_candidate_from_evidence(
            state,
            objective_findings,
            llm_candidate_diagnoses,
        )
        if (
            preferred_exact
            and self._is_specific_diagnosis(preferred_exact)
            and has_direct_diagnosis_support(support_text, preferred_exact)
        ):
            return preferred_exact

        exact_candidates = []
        seen_canonicals: set[str] = set()
        for diagnosis in [preferred_exact, deterministic_candidate, refined_diagnosis, *llm_candidate_diagnoses]:
            label = str(diagnosis).strip()
            if not self._is_specific_diagnosis(label):
                continue
            canonical = canonicalize_diagnosis_text(label)
            if canonical in seen_canonicals:
                continue
            seen_canonicals.add(canonical)
            exact_candidates.append(label)

        for label in exact_candidates:
            if has_direct_diagnosis_support(support_text, label):
                return label

        if objective_count >= 2 and len(exact_candidates) == 1:
            return exact_candidates[0]

        if (
            objective_count >= 2
            and preferred_exact
            and self._is_specific_diagnosis(preferred_exact)
            and len(exact_candidates) <= 2
        ):
            return preferred_exact
        return ""

    def _count_keyword_matches(self, text: str, keywords: list[str]) -> int:
        return sum(1 for keyword in keywords if keyword and keyword in text)

    def _generic_fallback_rule_matches(self, text: str, rule: dict[str, Any]) -> bool:
        any_keywords = [str(item).strip().lower() for item in rule.get("any_keywords", []) if str(item).strip()]
        if any_keywords and not any(keyword in text for keyword in any_keywords):
            return False

        all_keywords = [str(item).strip().lower() for item in rule.get("all_keywords", []) if str(item).strip()]
        if all_keywords and not all(keyword in text for keyword in all_keywords):
            return False

        group_sets_all = [
            [str(item).strip().lower() for item in group if str(item).strip()]
            for group in rule.get("group_sets_all", []) or []
            if isinstance(group, list)
        ]
        for group in group_sets_all:
            if group and not any(keyword in text for keyword in group):
                return False

        match_keywords = [str(item).strip().lower() for item in rule.get("match_keywords", []) if str(item).strip()]
        min_match_count = int(rule.get("min_match_count", 0) or 0)
        if match_keywords and min_match_count > 0:
            if self._count_keyword_matches(text, match_keywords) < min_match_count:
                return False

        primary_keywords = [str(item).strip().lower() for item in rule.get("primary_keywords", []) if str(item).strip()]
        min_primary_match_count = int(rule.get("min_primary_match_count", 0) or 0)
        if primary_keywords and min_primary_match_count > 0:
            if self._count_keyword_matches(text, primary_keywords) < min_primary_match_count:
                return False

        return any([any_keywords, all_keywords, group_sets_all, match_keywords, primary_keywords])

    def _config_generic_fallback_diagnosis(self, text: str) -> str:
        rules = get_specialty_generic_fallback_rules(self.department)
        for rule in rules:
            diagnosis = str(rule.get("diagnosis", "")).strip()
            if not diagnosis:
                continue
            if self._generic_fallback_rule_matches(text, rule):
                return diagnosis
        return ""

    def _choose_specialty_finalize_action(
        self,
        *,
        state: dict[str, Any],
        refined_diagnosis: str,
        deterministic_candidate: str,
        objective_findings: list[str],
        next_test: str,
        llm_candidate_diagnoses: list[str],
    ) -> tuple[str, str, str]:
        support_text = self._specialty_support_text(state, objective_findings, refined_diagnosis)
        has_specific = self._is_specific_diagnosis(refined_diagnosis)
        has_direct_support = has_specific and has_direct_diagnosis_support(support_text, refined_diagnosis)
        exact_candidates = [
            str(item).strip()
            for item in llm_candidate_diagnoses
            if self._is_specific_diagnosis(str(item).strip())
        ]
        best_commit = self._best_committable_specialty_diagnosis(
            state=state,
            refined_diagnosis=refined_diagnosis,
            deterministic_candidate=deterministic_candidate,
            objective_findings=objective_findings,
            llm_candidate_diagnoses=llm_candidate_diagnoses,
        )

        if best_commit and objective_findings:
            return (
                "diagnose_now",
                "",
                "The specialty service already has a committable exact diagnosis with direct objective support, so finalizing now is justified.",
            )
        if str(next_test).strip() and (not has_specific or not has_direct_support):
            return (
                "request_test",
                str(next_test).strip(),
                "The specialty diagnosis is still not decisively supported, so one focused specialty test is more useful than finalizing immediately.",
            )
        if not has_specific or len(exact_candidates) > 1 or len(objective_findings) >= 2:
            return (
                "refine_again",
                "",
                "Current specialty evidence is substantial but not fully decisive, so one more refinement pass is justified before finalizing.",
            )
        return (
            "diagnose_now",
            "",
            "No additional specialty action is likely to change the leading diagnosis enough to justify delaying the decision.",
        )

    def _choose_specialty_next_step_action(
        self,
        *,
        state: dict[str, Any],
        refined_diagnosis: str,
        deterministic_candidate: str,
        objective_findings: list[str],
        next_test: str,
        can_ask_patient: bool,
        llm_candidate_diagnoses: list[str],
    ) -> tuple[str, str, str]:
        support_text = self._specialty_support_text(state, objective_findings, refined_diagnosis)
        has_specific = self._is_specific_diagnosis(refined_diagnosis)
        has_direct_support = has_specific and has_direct_diagnosis_support(support_text, refined_diagnosis)
        best_commit = self._best_committable_specialty_diagnosis(
            state=state,
            refined_diagnosis=refined_diagnosis,
            deterministic_candidate=deterministic_candidate,
            objective_findings=objective_findings,
            llm_candidate_diagnoses=llm_candidate_diagnoses,
        )

        if best_commit and objective_findings:
            return (
                "diagnose_now",
                "",
                "Current specialty evidence already supports an exact diagnosis strongly enough to finalize without another step.",
            )
        if str(next_test).strip():
            return (
                "request_test",
                str(next_test).strip(),
                "The next most useful specialty action is one focused test because the current evidence is still incomplete.",
            )
        if can_ask_patient:
            return (
                "ask_patient",
                "",
                "A single focused specialty history question is still informative before finalizing.",
            )
        return (
            "diagnose_now",
            "",
            "No additional specialty step is likely to add decisive information beyond the current evidence.",
        )

    def _apply_specialty_finalize_override(
        self,
        what_if_override: Optional[dict[str, Any]],
        *,
        turn_index: int,
        proposed_action: str,
        proposed_target: str,
        proposed_rationale: str,
    ) -> tuple[str, str, str, Optional[dict[str, Any]]]:
        if not self._matches_what_if_override(what_if_override, node="specialty_finalize", turn_index=turn_index):
            return proposed_action, proposed_target, proposed_rationale, None

        selected_action = dict((what_if_override or {}).get("selected_action", {}) or {})
        action_type = str(selected_action.get("type", "")).strip()
        action_target = str(selected_action.get("target", "")).strip()
        if not action_type:
            return proposed_action, proposed_target, proposed_rationale, None

        applied_rationale = (
            f"User-selected what-if override at specialty_finalize: {action_type}"
            + (f" -> {action_target}" if action_target else "")
        )
        applied_event = {
            "mode": "replay",
            "node": "specialty_finalize",
            "turn_index": turn_index,
            "original_action": {
                "type": str(proposed_action).strip(),
                "target": str(proposed_target).strip(),
                "rationale": str(proposed_rationale).strip(),
            },
            "selected_action": {
                "type": action_type,
                "target": action_target,
                "rationale": applied_rationale,
            },
            "applied": True,
        }
        what_if_override["consumed"] = True
        return action_type, action_target, applied_rationale, applied_event

    def _apply_specialty_next_step_override(
        self,
        what_if_override: Optional[dict[str, Any]],
        *,
        turn_index: int,
        proposed_action: str,
        proposed_target: str,
        proposed_rationale: str,
    ) -> tuple[str, str, str, Optional[dict[str, Any]]]:
        if not self._matches_what_if_override(what_if_override, node="specialty_next_step", turn_index=turn_index):
            return proposed_action, proposed_target, proposed_rationale, None

        selected_action = dict((what_if_override or {}).get("selected_action", {}) or {})
        action_type = str(selected_action.get("type", "")).strip()
        action_target = str(selected_action.get("target", "")).strip()
        if not action_type:
            return proposed_action, proposed_target, proposed_rationale, None

        applied_rationale = (
            f"User-selected what-if override at specialty_next_step: {action_type}"
            + (f" -> {action_target}" if action_target else "")
        )
        applied_event = {
            "mode": "replay",
            "node": "specialty_next_step",
            "turn_index": turn_index,
            "original_action": {
                "type": str(proposed_action).strip(),
                "target": str(proposed_target).strip(),
                "rationale": str(proposed_rationale).strip(),
            },
            "selected_action": {
                "type": action_type,
                "target": action_target,
                "rationale": applied_rationale,
            },
            "applied": True,
        }
        what_if_override["consumed"] = True
        return action_type, action_target, applied_rationale, applied_event

    def _execute_specialty_test(
        self,
        local_state: dict[str, Any],
        specialty_steps: list[dict[str, Any]],
        *,
        requested_test: str,
        rationale: str,
        test_module: Any,
    ) -> bool:
        if test_module is None or not str(requested_test).strip():
            return False
        resolved_name, result_text = test_module.request_test(requested_test)
        finding = f"{resolved_name or requested_test}: {result_text}"
        if finding not in local_state["objective_findings"]:
            local_state["objective_findings"].append(finding)
        normalized_requested = str(resolved_name or requested_test).strip()
        if normalized_requested and normalized_requested not in local_state["requested_tests"]:
            local_state["requested_tests"].append(normalized_requested)
        self._append_local_known_information(local_state, finding)
        specialty_steps.append(
            {
                "action": "request_test",
                "rationale": str(rationale).strip(),
                "requested_test": requested_test,
                "resolved_name": resolved_name or requested_test,
                "result_text": result_text,
            }
        )
        return True

    def _parse_specialty_llm_response(self, response: str) -> tuple[str, str, str]:
        text = str(response or "").strip()
        if not text:
            return "", "", "empty"

        cleaned = re.sub(r"```(?:json|text)?", "", text, flags=re.IGNORECASE).replace("```", "").strip()

        try:
            parsed = json.loads(cleaned)
            refined_diagnosis = str(parsed.get("refined_diagnosis", "")).strip()
            diagnostic_plan = str(parsed.get("diagnostic_plan", "")).strip()
            if refined_diagnosis and diagnostic_plan:
                return refined_diagnosis, diagnostic_plan, "json"
        except Exception:
            pass

        diagnosis_match = re.search(
            r"REFINED_DIAGNOSIS\s*:\s*(.+)",
            cleaned,
            flags=re.IGNORECASE,
        )
        plan_match = re.search(
            r"DIAGNOSTIC_PLAN\s*:\s*(.+)",
            cleaned,
            flags=re.IGNORECASE,
        )
        refined_diagnosis = diagnosis_match.group(1).strip() if diagnosis_match else ""
        diagnostic_plan = plan_match.group(1).strip() if plan_match else ""
        if refined_diagnosis and diagnostic_plan:
            return refined_diagnosis, diagnostic_plan, "labeled"

        return "", "", "unstructured"

    def _build_llm_candidate_diagnoses(
        self,
        state: dict[str, Any],
        working_diagnosis: str,
        objective_findings: list[str],
        deterministic_candidate: str,
    ) -> list[str]:
        candidates: list[str] = []
        objective_text = "\n".join(objective_findings)
        concise_history = " ".join(str(item).strip() for item in state.get("known_information", [])[-2:] if str(item).strip())
        evidence_text = " ".join(
            [
                self._department_evidence_text(state, working_diagnosis, objective_findings),
                concise_history,
            ]
        ).strip()
        catalog_query = " ".join(
            [
                working_diagnosis,
                deterministic_candidate,
                objective_text,
                " ".join(str(item).strip() for item in state.get("working_problem_list", []) if str(item).strip()),
                concise_history,
            ]
        ).strip()

        for diagnosis in extract_known_diagnoses(objective_text, limit=3):
            if diagnosis not in candidates:
                candidates.append(diagnosis)

        evidence_hint = infer_catalog_diagnosis_from_evidence(objective_text)
        if evidence_hint and self._is_specific_diagnosis(evidence_hint) and evidence_hint not in candidates:
            candidates.append(evidence_hint)

        allowed_departments = [self.department]
        routing_scores = {
            str(key).strip(): float(value)
            for key, value in (state.get("department_routing_scores", {}) or {}).items()
            if str(key).strip()
        }
        for department, _score in rank_department_scores(routing_scores)[:2]:
            normalized_department = normalize_department(department, default="")
            if normalized_department and normalized_department not in allowed_departments:
                allowed_departments.append(normalized_department)

        for diagnosis in candidates:
            assignment = get_curated_department_assignment(diagnosis)
            if not assignment:
                continue
            normalized_department = normalize_department(str(assignment.get("department", "")).strip(), default="")
            if normalized_department and normalized_department not in allowed_departments:
                allowed_departments.append(normalized_department)

        for diagnosis in search_known_diagnoses(
            objective_text,
            limit=5,
            min_score=0.18,
            allowed_departments=allowed_departments,
        ):
            if diagnosis not in candidates and self._is_runtime_candidate_allowed(diagnosis):
                candidates.append(diagnosis)

        for diagnosis in search_known_diagnoses(
            catalog_query,
            limit=8,
            min_score=0.24,
            allowed_departments=allowed_departments,
        ):
            if diagnosis not in candidates and self._is_runtime_candidate_allowed(diagnosis):
                candidates.append(diagnosis)

        for diagnosis in [deterministic_candidate, working_diagnosis]:
            normalized = str(diagnosis).strip()
            if not normalized or normalized in candidates:
                continue
            if self._is_specific_diagnosis(normalized):
                evidence_gate_text = " ".join(
                    [
                        objective_text,
                        str(state.get("arrival_info", "")).strip(),
                        str((state.get("ipass_handoff", {}) or {}).get("patient_summary", "")).strip(),
                        self._history_rescue_query(state),
                    ]
                ).strip()
                if not has_direct_diagnosis_support(evidence_gate_text, normalized):
                    continue
            if normalized not in candidates:
                candidates.append(normalized)

        pattern_filter_text = " ".join(
            [
                objective_text,
                str(state.get("arrival_info", "")).strip(),
                str((state.get("ipass_handoff", {}) or {}).get("patient_summary", "")).strip(),
                self._history_rescue_query(state),
            ]
        ).strip()
        candidates = self._filter_exact_candidates_by_pattern(pattern_filter_text, candidates)
        guarded_candidates: list[str] = []
        for diagnosis in candidates:
            label = str(diagnosis).strip()
            if not label:
                continue
            if (
                self._requires_direct_support_for_exact_candidate(label)
                and self._is_specific_diagnosis(label)
                and not has_direct_diagnosis_support(pattern_filter_text, label)
            ):
                continue
            guarded_candidates.append(label)
        candidates = guarded_candidates

        generic_only = self._candidate_list_is_generic_only(candidates)
        if generic_only and self.department not in {"general_medicine", "internal_medicine"}:
            history_rescue_query = self._history_rescue_query(state)
            for diagnosis in search_known_diagnoses(
                history_rescue_query,
                limit=5,
                min_score=0.12,
                allowed_departments=[self.department],
            ):
                if diagnosis not in candidates and self._is_runtime_candidate_allowed(diagnosis):
                    candidates.append(diagnosis)

            broader_query = " ".join(
                [
                    catalog_query,
                    history_rescue_query,
                    str((state.get("ipass_handoff", {}) or {}).get("patient_summary", "")).strip(),
                    str(state.get("arrival_info", "")).strip(),
                    str((state.get("ipass_handoff", {}) or {}).get("receiver_synthesis_target", "")).strip(),
                ]
            ).strip()
            for diagnosis in search_known_diagnoses(
                broader_query,
                limit=6,
                min_score=0.18,
                allowed_departments=[self.department],
            ):
                if diagnosis not in candidates and self._is_runtime_candidate_allowed(diagnosis):
                    candidates.append(diagnosis)

            if self._candidate_list_is_generic_only(candidates):
                global_rescue: list[str] = []
                for diagnosis in search_known_diagnoses(
                    broader_query,
                    limit=10,
                    min_score=0.1,
                    allowed_departments=None,
                ):
                    assignment = get_curated_department_assignment(diagnosis)
                    if not assignment:
                        continue
                    owning_department = normalize_department(str(assignment.get("department", "")).strip(), default="")
                    if owning_department != self.department:
                        continue
                    if not self._is_runtime_candidate_allowed(diagnosis):
                        continue
                    global_rescue.append(diagnosis)
                    if len(global_rescue) >= 3:
                        break
                for diagnosis in global_rescue:
                    if diagnosis not in candidates:
                        candidates.append(diagnosis)

        # If general/internal medicine only has generic placeholders, broaden the shortlist
        # so the service can still escape "undifferentiated acute complaint" using catalog evidence.
        generic_only = self._candidate_list_is_generic_only(candidates)
        if self.department in {"general_medicine", "internal_medicine"} and generic_only:
            broadened_query = " ".join(
                [
                    catalog_query,
                    str((state.get("ipass_handoff", {}) or {}).get("patient_summary", "")).strip(),
                    str(state.get("arrival_info", "")).strip(),
                ]
            ).strip()
            for diagnosis in search_known_diagnoses(
                broadened_query,
                limit=6,
                min_score=0.22,
                allowed_departments=None,
            ):
                if diagnosis not in candidates and self._is_runtime_candidate_allowed(diagnosis):
                    candidates.append(diagnosis)

        return candidates[:8]

    def _choose_secondary_consult_department(
        self,
        state: dict[str, Any],
        working_diagnosis: str,
        refined_diagnosis: str,
        objective_findings: list[str],
    ) -> str:
        routing_scores = {
            str(key).strip(): float(value)
            for key, value in (state.get("department_routing_scores", {}) or {}).items()
            if str(key).strip()
        }
        evidence_scores = infer_department_scores_by_source(
            {
                "working_diagnosis": working_diagnosis,
                "supported_diagnosis": refined_diagnosis if self._is_specific_diagnosis(refined_diagnosis) else "",
                "objective_findings": objective_findings,
                "known_information": [str(item).strip() for item in state.get("known_information", [])[-4:] if str(item).strip()],
            },
            prefer_clinical_department=True,
        )
        combined_scores = dict(routing_scores)
        for department, score in evidence_scores.items():
            combined_scores[department] = combined_scores.get(department, 0.0) + float(score)

        ranked = rank_department_scores(combined_scores)
        if not ranked:
            return ""

        top_department, top_score = ranked[0]
        current_score = combined_scores.get(self.department, 0.0)
        if top_department != self.department and (top_score - current_score) >= 1.5:
            return normalize_department(top_department, default="")

        if not self._is_specific_diagnosis(refined_diagnosis):
            for department, score in ranked:
                normalized = normalize_department(department, default="")
                if normalized and normalized != self.department and score >= 2.0:
                    return normalized
        return ""

    def _apply_secondary_consult(
        self,
        state: dict[str, Any],
        transcript: list[dict[str, str]],
        refined_diagnosis: str,
        objective_findings: list[str],
        specialty_steps: list[dict[str, Any]],
        llm_attempted: bool,
        used_llm: bool,
        llm_failure_reason: str,
    ) -> tuple[str, str, bool]:
        secondary_department = self._choose_secondary_consult_department(
            state,
            str(state.get("er_working_diagnosis", "")).strip() or refined_diagnosis,
            refined_diagnosis,
            objective_findings,
        )
        if not secondary_department:
            return refined_diagnosis, self.department, False

        opinion = SpecialtyAgent().consult(secondary_department, state, transcript)
        specialty_steps.append(
            {
                "action": "consult_specialty",
                "rationale": "The receiving specialty still sees routing uncertainty, so it requests one focused cross-specialty opinion before finalizing.",
                "consult_department": secondary_department,
                "opinion": opinion,
            }
        )
        state.setdefault("consultation_history", []).append(
            {"department": secondary_department, "opinion": opinion}
        )
        self._append_local_known_information(state, f"{secondary_department} consult: {opinion}")

        consulted_diagnosis = match_known_diagnosis(opinion) or (
            extract_known_diagnoses(opinion, limit=1)[0] if extract_known_diagnoses(opinion, limit=1) else ""
        )
        if consulted_diagnosis:
            return consulted_diagnosis, secondary_department, True

        return refined_diagnosis, self.department, True

    def _normalize_llm_diagnosis_candidate(self, diagnosis: str) -> str:
        text = str(diagnosis).strip()
        if not text:
            return ""

        cleaned = re.sub(
            r"^(diagnosis|final diagnosis|most likely diagnosis|likely diagnosis|refined_diagnosis)\s*[:\-]?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()
        cleaned = cleaned.strip("* ").strip()
        hedged = re.sub(
            r"^(possible|probable|likely|most likely|suspected|consistent with)\s+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()

        for candidate in [text, cleaned, hedged]:
            matched = match_known_diagnosis(candidate)
            if matched:
                return matched

        for candidate in [text, cleaned, hedged]:
            extracted = extract_known_diagnoses(candidate, limit=1)
            if extracted:
                return extracted[0]

        for candidate in [text, cleaned, hedged]:
            department_limited = search_known_diagnoses(
                candidate,
                limit=1,
                min_score=0.18,
                allowed_departments=[self.department],
            )
            if department_limited:
                return department_limited[0]

        if any(marker in cleaned.lower() for marker in ["findings", "{", "}", "result", "present (", "elevated", "normal"]):
            return ""
        return hedged or cleaned

    def _candidate_list_is_generic_only(self, candidates: list[str]) -> bool:
        cleaned = [str(item).strip() for item in candidates if str(item).strip()]
        if not cleaned:
            return True
        return not any(self._is_specific_diagnosis(item) for item in cleaned)

    def _has_specific_candidate(self, candidates: list[str]) -> bool:
        return any(self._is_specific_diagnosis(str(item).strip()) for item in candidates if str(item).strip())

    def _is_acceptable_llm_diagnosis(
        self,
        normalized_diagnosis: str,
        candidates: list[str],
        deterministic_candidate: str,
    ) -> bool:
        diagnosis = str(normalized_diagnosis).strip()
        if not diagnosis:
            return False

        if diagnosis in candidates:
            return True

        matched = match_known_diagnosis(diagnosis)
        if matched and matched in candidates:
            return True

        diagnosis_canonical = canonicalize_diagnosis_text(diagnosis)
        matched_canonical = canonicalize_diagnosis_text(matched) if matched else ""
        candidate_canonicals = {
            canonicalize_diagnosis_text(str(candidate).strip())
            for candidate in candidates
            if str(candidate).strip()
        }
        if diagnosis_canonical and diagnosis_canonical in candidate_canonicals:
            return True
        if matched_canonical and matched_canonical in candidate_canonicals:
            return True

        deterministic = str(deterministic_candidate).strip()
        if deterministic and diagnosis == deterministic:
            return True

        if matched and self._candidate_list_is_generic_only(candidates):
            assignment = get_curated_department_assignment(matched)
            if assignment:
                matched_department = normalize_department(str(assignment.get("department", "")).strip(), default="")
                if matched_department == self.department:
                    return True

        if self._candidate_list_is_generic_only(candidates):
            assignment = get_curated_department_assignment(diagnosis)
            if assignment:
                matched_department = normalize_department(str(assignment.get("department", "")).strip(), default="")
                if matched_department == self.department:
                    return True

        if matched and self._has_specific_candidate(candidates):
            assignment = get_curated_department_assignment(matched)
            if assignment:
                matched_department = normalize_department(str(assignment.get("department", "")).strip(), default="")
                if matched_department == self.department:
                    return True

        return False

    def _llm_refine_diagnosis(
        self,
        state: dict[str, Any],
        transcript: list[dict[str, str]],
        working_diagnosis: str,
        objective_findings: list[str],
        deterministic_candidate: str,
    ) -> dict[str, str]:
        if not settings.USE_LLM_FOR_SPECIALTY_DEPARTMENT_AGENT:
            return {}
        ipass_handoff = self._compact_ipass_handoff(state)
        if not objective_findings and not ipass_handoff.get("patient_summary"):
            return {}

        candidate_diagnoses = self._build_llm_candidate_diagnoses(
            state,
            working_diagnosis,
            objective_findings,
            deterministic_candidate,
        )
        key_findings = objective_findings[-2:] or [
            str(item).strip()
            for item in ipass_handoff.get("situation_awareness", [])[:2]
            if str(item).strip()
        ]
        payload = {
            "department": self.department,
            "patient_summary": str(ipass_handoff.get("patient_summary", "")).strip(),
            "candidate_diagnoses": candidate_diagnoses,
            "key_findings": key_findings,
            "receiver_target": str(ipass_handoff.get("receiver_synthesis_target", "")).strip(),
        }
        evidence_support_text = " ".join(
            [
                "\n".join(objective_findings),
                str(state.get("arrival_info", "")).strip(),
                str((state.get("ipass_handoff", {}) or {}).get("patient_summary", "")).strip(),
                self._history_rescue_query(state),
            ]
        ).strip()
        preferred_exact_candidate = self._preferred_exact_candidate_from_evidence(
            state,
            objective_findings,
            candidate_diagnoses,
        )
        try:
            response = self.client.chat(
                f"{self.system_prompt}\n\n{self.department_prompt}",
                json.dumps(payload, ensure_ascii=False, indent=2),
                model=settings.SPECIALTY_OLLAMA_MODEL,
            ).strip()
            refined_diagnosis, diagnostic_plan, parse_mode = self._parse_specialty_llm_response(response)
            normalized_diagnosis = self._normalize_llm_diagnosis_candidate(refined_diagnosis)
            if (
                normalized_diagnosis
                and not self._is_specific_diagnosis(normalized_diagnosis)
                and self._is_specific_diagnosis(deterministic_candidate)
                and has_direct_diagnosis_support(evidence_support_text, deterministic_candidate)
            ):
                normalized_diagnosis = deterministic_candidate
            if (
                preferred_exact_candidate
                and self._is_specific_diagnosis(preferred_exact_candidate)
                and normalized_diagnosis
                and canonicalize_diagnosis_text(normalized_diagnosis) != canonicalize_diagnosis_text(preferred_exact_candidate)
                and has_direct_diagnosis_support(evidence_support_text, preferred_exact_candidate)
                and not has_direct_diagnosis_support(evidence_support_text, normalized_diagnosis)
            ):
                normalized_diagnosis = preferred_exact_candidate
            if parse_mode in {"json", "labeled"} and normalized_diagnosis and diagnostic_plan and self._is_acceptable_llm_diagnosis(
                normalized_diagnosis,
                candidate_diagnoses,
                deterministic_candidate,
            ):
                if (
                    self._requires_direct_support_for_exact_candidate(normalized_diagnosis)
                    and not has_direct_diagnosis_support(evidence_support_text, normalized_diagnosis)
                ):
                    return {
                        "attempted": True,
                        "used_llm": False,
                        "failure_reason": "llm_response_guarded_exact_without_support",
                        "response_preview": response[:240],
                        "candidate_diagnoses": candidate_diagnoses,
                    }
                return {
                    "attempted": True,
                    "refined_diagnosis": normalized_diagnosis,
                    "diagnostic_plan": diagnostic_plan,
                    "used_llm": True,
                    "response_preview": response[:240],
                    "candidate_diagnoses": candidate_diagnoses,
                }
            return {
                "attempted": True,
                "used_llm": False,
                "failure_reason": f"llm_response_{parse_mode}_or_unsupported",
                "response_preview": response[:240],
                "candidate_diagnoses": candidate_diagnoses,
            }
        except Exception as exc:
            return {
                "attempted": True,
                "used_llm": False,
                "failure_reason": f"llm_exception:{type(exc).__name__}",
                "candidate_diagnoses": candidate_diagnoses,
            }
        return {}

    def _refine_diagnosis(
        self,
        state: dict[str, Any],
        transcript: list[dict[str, str]],
        working_diagnosis: str,
    ) -> str:
        objective_findings = [str(item).strip() for item in state.get("objective_findings", []) if str(item).strip()]
        objective_text = "\n".join(objective_findings)
        evidence_hint = infer_catalog_diagnosis_from_evidence(objective_text) if objective_text else None
        if (
            self._is_specific_diagnosis(working_diagnosis)
            and evidence_hint
            and canonicalize_diagnosis_text(working_diagnosis) == canonicalize_diagnosis_text(evidence_hint)
        ):
            return working_diagnosis
        if self._is_specific_diagnosis(working_diagnosis) and objective_text:
            support_text = " ".join(
                [
                    objective_text,
                    str(state.get("arrival_info", "")).strip(),
                    str((state.get("ipass_handoff", {}) or {}).get("patient_summary", "")).strip(),
                    self._history_rescue_query(state),
                ]
            ).strip()
            if has_direct_diagnosis_support(support_text, working_diagnosis):
                return working_diagnosis
        if objective_text:
            extracted = extract_known_diagnoses(objective_text, limit=1)
            if extracted and has_direct_diagnosis_support(objective_text, extracted[0]):
                return extracted[0]

        text = self._department_evidence_text(state, working_diagnosis, objective_findings)
        combined_hint = infer_catalog_diagnosis_from_evidence(text)
        if combined_hint and self._is_specific_diagnosis(combined_hint):
            return combined_hint

        if objective_findings and (
            not self._is_specific_diagnosis(working_diagnosis)
            or not has_direct_diagnosis_support(
                " ".join(
                    [
                        objective_text,
                        str(state.get("arrival_info", "")).strip(),
                        str((state.get("ipass_handoff", {}) or {}).get("patient_summary", "")).strip(),
                        self._history_rescue_query(state),
                    ]
                ).strip(),
                working_diagnosis,
            )
        ):
            exact_shortlist = search_known_diagnoses(
                " ".join(
                    [
                        objective_text,
                        text,
                        str((state.get("ipass_handoff", {}) or {}).get("patient_summary", "")).strip(),
                        str(state.get("arrival_info", "")).strip(),
                    ]
                ).strip(),
                limit=3,
                min_score=0.18,
                allowed_departments=[self.department],
            )
            for diagnosis in exact_shortlist:
                if self._is_specific_diagnosis(diagnosis):
                    return diagnosis

        if self._is_specific_diagnosis(working_diagnosis) and not objective_text:
            return working_diagnosis

        config_fallback = self._config_generic_fallback_diagnosis(text)
        if config_fallback:
            return config_fallback

        return working_diagnosis or "undifferentiated acute complaint"

    def accept_handoff(
        self,
        state: dict[str, Any],
        transcript: list[dict[str, str]],
        patient_agent: Optional[Any] = None,
        test_module: Optional[Any] = None,
        max_turns: int = 2,
        what_if_override: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        local_state = {
            **state,
            "known_information": list(state.get("known_information", []) or []),
            "objective_findings": list(state.get("objective_findings", []) or []),
            "requested_tests": list(state.get("requested_tests", []) or []),
            "requested_exams": list(state.get("requested_exams", []) or []),
        }
        working_diagnosis, objective_findings = self._collect_context(local_state, transcript)
        ipass_handoff = self._compact_ipass_handoff(local_state)
        focus = get_specialty_diagnostic_focus(
            self.department,
            "refining the department-level differential using the ER evidence already gathered",
        )
        next_step = get_specialty_next_step_prompt(
            self.department,
            "review the ER findings and propose the most useful next diagnostic clarification",
        )

        evidence_basis = "objective ER findings are already available" if objective_findings else "the handoff currently relies mostly on ER history and early assessment"
        specialty_steps: list[dict[str, Any]] = []
        used_llm = False
        llm_attempted = False
        llm_failure_reason = ""
        llm_response_preview = ""
        llm_candidate_diagnoses: list[str] = []
        specialty_progress = False
        specialty_interview_count = 0
        specialty_consult_count = 0
        refined_diagnosis = working_diagnosis
        responsible_department = self.department
        decision_snapshots: list[dict[str, Any]] = []
        what_if_applied_event: Optional[dict[str, Any]] = None

        for _ in range(max(1, int(max_turns or 1))):
            objective_findings = [str(item).strip() for item in local_state.get("objective_findings", []) if str(item).strip()]
            deterministic_candidate = self._refine_diagnosis(
                local_state,
                transcript,
                working_diagnosis,
            )

            llm_refinement = self._llm_refine_diagnosis(
                local_state,
                transcript,
                working_diagnosis,
                objective_findings,
                deterministic_candidate,
            )
            if llm_refinement:
                llm_attempted = bool(llm_refinement.get("attempted", False)) or llm_attempted
                refined_diagnosis = str(llm_refinement.get("refined_diagnosis", "")).strip() or deterministic_candidate
                used_llm = bool(llm_refinement.get("used_llm", False))
                llm_failure_reason = (
                    ""
                    if used_llm
                    else str(llm_refinement.get("failure_reason", "")).strip() or llm_failure_reason
                )
                llm_response_preview = str(llm_refinement.get("response_preview", "")).strip() or llm_response_preview
                llm_candidate_diagnoses = list(llm_refinement.get("candidate_diagnoses", []) or llm_candidate_diagnoses)
            else:
                refined_diagnosis = deterministic_candidate

            if self._is_specific_diagnosis(refined_diagnosis) and objective_findings:
                specialty_steps.append(
                    {
                        "action": "diagnose",
                        "rationale": "The specialty department now has enough ER and specialty-level evidence to finalize the diagnosis.",
                        "diagnosis": refined_diagnosis,
                    }
                )
                break

            if specialty_consult_count < 1:
                updated_diagnosis, updated_department, consult_used = self._apply_secondary_consult(
                    local_state,
                    transcript,
                    refined_diagnosis,
                    objective_findings,
                    specialty_steps,
                    llm_attempted,
                    used_llm,
                    llm_failure_reason,
                )
                if consult_used:
                    specialty_consult_count += 1
                if updated_department != self.department or updated_diagnosis != refined_diagnosis:
                    specialty_progress = True
                    refined_diagnosis = updated_diagnosis or refined_diagnosis
                    responsible_department = updated_department or responsible_department
                    working_diagnosis = refined_diagnosis
                    continue

            next_test = self._choose_additional_test(local_state, test_module)
            can_ask_patient = patient_agent is not None and specialty_interview_count < 1
            specialty_turn_index = int(state.get("turn_count", 0) or 0) + len(specialty_steps) + 1
            proposed_action, proposed_target, proposed_rationale = self._choose_specialty_next_step_action(
                state=local_state,
                refined_diagnosis=refined_diagnosis,
                deterministic_candidate=deterministic_candidate,
                objective_findings=objective_findings,
                next_test=next_test,
                can_ask_patient=can_ask_patient,
                llm_candidate_diagnoses=llm_candidate_diagnoses,
            )
            decision_snapshots.append(
                self.what_if_module.build_specialty_next_step_snapshot(
                    state_dict=local_state,
                    transcript=transcript,
                    department=responsible_department,
                    working_diagnosis=refined_diagnosis,
                    proposed_action=proposed_action,
                    proposed_target=proposed_target,
                    proposed_rationale=proposed_rationale,
                    turn_index=specialty_turn_index,
                    case_id=str(state.get("case_id", "")).strip(),
                    next_test=next_test,
                    can_ask_patient=can_ask_patient,
                )
            )
            selected_action, selected_target, selected_rationale, applied_event = self._apply_specialty_next_step_override(
                what_if_override,
                turn_index=specialty_turn_index,
                proposed_action=proposed_action,
                proposed_target=proposed_target,
                proposed_rationale=proposed_rationale,
            )
            if applied_event is not None:
                what_if_applied_event = applied_event

            if selected_action == "diagnose_now":
                committed_diagnosis = self._best_committable_specialty_diagnosis(
                    state=local_state,
                    refined_diagnosis=refined_diagnosis,
                    deterministic_candidate=deterministic_candidate,
                    objective_findings=objective_findings,
                    llm_candidate_diagnoses=llm_candidate_diagnoses,
                )
                if committed_diagnosis:
                    refined_diagnosis = committed_diagnosis
                specialty_steps.append(
                    {
                        "action": "diagnose",
                        "rationale": selected_rationale,
                        "diagnosis": refined_diagnosis,
                    }
                )
                break

            if selected_action == "ask_patient" and patient_agent is not None and specialty_interview_count < 1:
                question = self._choose_interview_question(local_state)
                answer = str(patient_agent.answer(question)).strip()
                self._append_local_known_information(local_state, answer)
                specialty_steps.append(
                    {
                        "action": "ask_patient",
                        "rationale": selected_rationale,
                        "question": question,
                        "answer": answer,
                    }
                )
                specialty_interview_count += 1
                specialty_progress = True
                working_diagnosis = refined_diagnosis
                continue

            if selected_action == "request_test" and str(selected_target or next_test).strip():
                test_applied = self._execute_specialty_test(
                    local_state,
                    specialty_steps,
                    requested_test=str(selected_target or next_test).strip(),
                    rationale=selected_rationale,
                    test_module=test_module,
                )
                specialty_progress = specialty_progress or test_applied
                working_diagnosis = refined_diagnosis
                continue

            specialty_steps.append(
                {
                    "action": "diagnose",
                    "rationale": selected_rationale,
                    "diagnosis": refined_diagnosis,
                }
            )
            break

        objective_findings = [str(item).strip() for item in local_state.get("objective_findings", []) if str(item).strip()]
        specialty_turn_index = int(state.get("turn_count", 0) or 0) + len(specialty_steps) + 1
        proposed_next_test = self._choose_additional_test(local_state, test_module)
        proposed_action, proposed_target, proposed_rationale = self._choose_specialty_finalize_action(
            state=local_state,
            refined_diagnosis=refined_diagnosis or working_diagnosis,
            deterministic_candidate=refined_diagnosis or working_diagnosis,
            objective_findings=objective_findings,
            next_test=proposed_next_test,
            llm_candidate_diagnoses=llm_candidate_diagnoses,
        )
        decision_snapshots.append(
            self.what_if_module.build_specialty_finalize_snapshot(
                state_dict=local_state,
                transcript=transcript,
                department=responsible_department,
                refined_diagnosis=refined_diagnosis or working_diagnosis,
                proposed_action=proposed_action,
                proposed_target=proposed_target,
                proposed_rationale=proposed_rationale,
                turn_index=specialty_turn_index,
                case_id=str(state.get("case_id", "")).strip(),
                next_test=proposed_next_test,
                llm_candidate_diagnoses=llm_candidate_diagnoses,
            )
        )
        selected_action, selected_target, selected_rationale, what_if_applied_event = self._apply_specialty_finalize_override(
            what_if_override,
            turn_index=specialty_turn_index,
            proposed_action=proposed_action,
            proposed_target=proposed_target,
            proposed_rationale=proposed_rationale,
        )

        if specialty_steps and specialty_steps[-1].get("action") == "diagnose" and selected_action != "diagnose_now":
            specialty_steps.pop()

        if selected_action == "request_test" and str(selected_target).strip():
            test_applied = self._execute_specialty_test(
                local_state,
                specialty_steps,
                requested_test=selected_target,
                rationale=selected_rationale,
                test_module=test_module,
            )
            specialty_progress = specialty_progress or test_applied
            objective_findings = [str(item).strip() for item in local_state.get("objective_findings", []) if str(item).strip()]
        elif selected_action == "refine_again":
            specialty_steps.append(
                {
                    "action": "refine_again",
                    "rationale": selected_rationale,
                    "diagnosis": refined_diagnosis or working_diagnosis,
                }
            )
            specialty_progress = True
        else:
            if not specialty_steps or specialty_steps[-1].get("action") != "diagnose":
                specialty_steps.append(
                    {
                        "action": "diagnose",
                        "rationale": selected_rationale,
                        "diagnosis": refined_diagnosis or working_diagnosis,
                    }
                )

        if selected_action == "diagnose_now":
            committed_diagnosis = self._best_committable_specialty_diagnosis(
                state=local_state,
                refined_diagnosis=refined_diagnosis or working_diagnosis,
                deterministic_candidate=refined_diagnosis or working_diagnosis,
                objective_findings=objective_findings,
                llm_candidate_diagnoses=llm_candidate_diagnoses,
            )
            refined_diagnosis = committed_diagnosis or refined_diagnosis or working_diagnosis
        else:
            final_deterministic_candidate = self._refine_diagnosis(
                local_state,
                transcript,
                refined_diagnosis or working_diagnosis,
            )
            final_llm_refinement = self._llm_refine_diagnosis(
                local_state,
                transcript,
                refined_diagnosis or working_diagnosis,
                objective_findings,
                final_deterministic_candidate,
            )
            if final_llm_refinement:
                llm_attempted = bool(final_llm_refinement.get("attempted", False)) or llm_attempted
                refined_diagnosis = str(final_llm_refinement.get("refined_diagnosis", "")).strip() or refined_diagnosis
                used_llm = bool(final_llm_refinement.get("used_llm", False)) or used_llm
                llm_failure_reason = (
                    ""
                    if used_llm
                    else str(final_llm_refinement.get("failure_reason", "")).strip() or llm_failure_reason
                )
                llm_response_preview = str(final_llm_refinement.get("response_preview", "")).strip() or llm_response_preview
                llm_candidate_diagnoses = list(final_llm_refinement.get("candidate_diagnoses", []) or llm_candidate_diagnoses)
            else:
                refined_diagnosis = self._refine_diagnosis(
                    local_state,
                    transcript,
                    refined_diagnosis or working_diagnosis,
                )

            specialty_steps.append(
                {
                    "action": "diagnose",
                    "rationale": "The specialty service finalized the diagnosis after one last evidence-based refinement pass.",
                    "diagnosis": refined_diagnosis,
                }
            )
        curated_assignment = get_curated_department_assignment(refined_diagnosis)
        if self._is_specific_diagnosis(refined_diagnosis) and curated_assignment:
            curated_department = normalize_department(str(curated_assignment.get("department", "")).strip(), default="")
            if curated_department and curated_department != responsible_department:
                specialty_steps.append(
                    {
                        "action": "reroute_department",
                        "rationale": f"The final diagnosis is more consistent with {curated_department} ownership than {responsible_department}, so the receiving service re-aligns the case to the curated diagnostic owner.",
                        "from_department": responsible_department,
                        "to_department": curated_department,
                        "diagnosis": refined_diagnosis,
                    }
                )
                responsible_department = curated_department
        if specialty_steps and specialty_steps[-1].get("action") == "diagnose":
            specialty_steps[-1]["diagnosis"] = refined_diagnosis

        diagnostic_plan = (
            f"{responsible_department} reviews the ER handoff with the goal of {focus}. "
            f"Based on the current handoff, {evidence_basis}, and the next priority is to {next_step}."
        )
        if specialty_steps:
            action_sequence = " -> ".join(str(step.get("action", "")).strip() for step in specialty_steps if str(step.get("action", "")).strip())
            diagnostic_plan = (
                f"{responsible_department} reviewed the ER workup and followed this specialty path: {action_sequence}. "
                f"The current specialty conclusion is {refined_diagnosis}."
            )

        return {
            "accepting_service": responsible_department,
            "responsible_department": responsible_department,
            "working_diagnosis_received": working_diagnosis,
            "ipass_handoff_received": ipass_handoff,
            "refined_diagnosis": refined_diagnosis,
            "diagnostic_focus": focus,
            "diagnostic_plan": diagnostic_plan,
            "llm_attempted": llm_attempted,
            "used_llm": used_llm,
            "llm_failure_reason": llm_failure_reason,
            "llm_response_preview": llm_response_preview,
            "llm_candidate_diagnoses": llm_candidate_diagnoses,
            "specialty_steps": specialty_steps,
            "decision_snapshots": decision_snapshots,
            "what_if_applied_event": what_if_applied_event,
        }


class SpecialtyAgent:
    def __init__(self) -> None:
        self.client = OllamaClient(
            base_url=settings.SPECIALTY_BASE_URL,
            api_key=settings.SPECIALTY_API_KEY,
        )

    def _sanitize_history_fragment(self, text: str) -> str:
        cleaned = str(text).strip()
        if not cleaned:
            return ""
        cleaned = re.sub(r"\bI have a history of\b.*?(?:\.|$)", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bhas a history of\b.*?(?:\.|$)", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bfamily history\b.*?(?:\.|$)", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bpast medical history\b.*?(?:\.|$)", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _looks_meta_response(self, response: str) -> bool:
        text = str(response or "").strip().lower()
        meta_markers = [
            "this is a",
            "to answer the instruction",
            "here is",
            "example usage",
            "```",
            "json object",
            "simulation",
            "workflow",
            "python",
            "code",
        ]
        return any(marker in text for marker in meta_markers)

    def _normalize_specialty_response(self, response: str) -> str:
        text = str(response or "").strip()
        if not text:
            return ""
        text = re.sub(r"```(?:json|python|text)?", "", text, flags=re.IGNORECASE).replace("```", "").strip()
        text = re.sub(r"\s+", " ", text).strip()
        sentences = re.split(r"(?<=[.!?])\s+", text)
        trimmed = " ".join(sentence.strip() for sentence in sentences[:3] if sentence.strip()).strip()
        if not trimmed:
            trimmed = text
        if len(trimmed) > 400:
            trimmed = trimmed[:397].rstrip() + "..."
        return trimmed

    def _combined_text(self, state: dict[str, Any], transcript: list[dict[str, str]]) -> str:
        transcript_text = " ".join(str(entry.get("content", "")) for entry in transcript)
        state_text = " ".join(str(item) for item in state.get("known_information", []))
        suspected = " ".join(str(item) for item in state.get("suspected_diagnoses", []))
        return f"{state_text} {suspected} {transcript_text}".lower()

    def _fallback_opinion(self, department: str, state: dict[str, Any], transcript: list[dict[str, str]]) -> str:
        dept = normalize_department(department)
        objective_text = " ".join(str(item).strip() for item in state.get("objective_findings", []) if str(item).strip())
        history_fragments = [
            self._sanitize_history_fragment(str(item).strip())
            for item in state.get("known_information", []) or []
            if str(item).strip()
        ]
        history_text = " ".join(fragment for fragment in history_fragments if fragment)
        focused_text = " ".join([objective_text, str(state.get("arrival_info", "")).strip(), history_text]).strip()

        evidence_hint = infer_catalog_diagnosis_from_evidence(objective_text) or infer_catalog_diagnosis_from_evidence(focused_text)
        if evidence_hint:
            return (
                f"{dept} consult: the available evidence is most consistent with {evidence_hint}. "
                f"This specialty impression is based on the currently documented history and objective findings."
            )

        department_candidates = search_known_diagnoses(
            focused_text,
            limit=2,
            min_score=0.12,
            allowed_departments=[dept],
        )
        if department_candidates:
            lead = department_candidates[0]
            return (
                f"{dept} consult: the available evidence is most consistent with {lead}. "
                f"This specialty impression is based on the currently documented history and objective findings."
            )

        text = self._combined_text(state, transcript)
        diagnoses = extract_known_diagnoses(objective_text, limit=2) or extract_known_diagnoses(text, limit=2)

        if diagnoses:
            lead = diagnoses[0]
            return (
                f"{dept} consult: the available evidence is most consistent with {lead}. "
                f"This specialty impression is based on the currently documented history and objective findings."
            )

        if specialty_matches_keywords(dept, text):
            return (
                f"{dept} consult: the current presentation fits a {dept.replace('_', ' ')} problem pattern, "
                "but more objective confirmation may still be needed."
            )

        return (
            f"{dept} consult: there is not enough specialty-specific evidence yet for a confident diagnosis, "
            "but continued staged evaluation is reasonable."
        )

    def consult(self, department: str, state: dict[str, Any], transcript: list[dict[str, str]]) -> str:
        dept = normalize_department(department)
        fallback = self._fallback_opinion(dept, state, transcript)
        if not settings.USE_LLM_FOR_SPECIALTY_AGENT:
            return fallback

        payload = {
            "department": dept,
            "state": state,
            "transcript": transcript[-12:],
            "instruction": (
                "Return only the specialty opinion itself in 1 to 2 sentences. "
                "Do not mention prompts, workflows, simulations, examples, code, or formatting notes. "
                "Do not explain your process. If evidence is weak, say so briefly."
            ),
        }
        system_prompt = load_prompt(f"specialty/{dept}.txt", DEFAULT_DEPARTMENT_PROMPT_FALLBACK)
        try:
            response = self.client.chat(
                system_prompt,
                json.dumps(payload, ensure_ascii=False, indent=2),
                model=settings.SPECIALTY_OLLAMA_MODEL,
            ).strip()
            if self._looks_meta_response(response):
                return fallback
            normalized = self._normalize_specialty_response(response)
            if normalized:
                return normalized
        except Exception:
            pass
        return fallback
