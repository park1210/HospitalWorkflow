from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
import re
from typing import Any, Iterable

from app.config import settings
from app.llm.ollama_client import OllamaClient
from app.utils.department_catalog import infer_department_scores
from app.utils.prompt_loader import load_prompt


def _resolve_run_ids(run_ids: Iterable[str] | None = None) -> list[str]:
    if run_ids:
        values = [str(item).strip() for item in run_ids if str(item).strip()]
        if values:
            return values
    if not settings.RESULTS_DIR.exists():
        return []
    available = sorted(path.name for path in settings.RESULTS_DIR.iterdir() if path.is_dir())
    if not available:
        return []
    return [available[-1]]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_json_object(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        return raw[start : end + 1].strip()
    return raw


def _extract_string_field(text: str, key: str) -> str:
    pattern = rf'"{re.escape(key)}"\s*:\s*"((?:[^"\\]|\\.)*)"'
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return ""
    value = match.group(1)
    value = value.replace('\\"', '"').replace("\\n", " ").replace("\\t", " ")
    return _normalize_optional_text(value)


def _extract_list_field(text: str, key: str) -> list[str]:
    pattern = rf'"{re.escape(key)}"\s*:\s*\[(.*?)\]'
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return []
    inner = match.group(1)
    items = re.findall(r'"((?:[^"\\]|\\.)*)"', inner)
    values = []
    for item in items:
        value = item.replace('\\"', '"').replace("\\n", " ").replace("\\t", " ")
        normalized = _normalize_optional_text(value)
        if normalized:
            values.append(normalized)
    return values


def _fallback_parse_reflection_output(text: str, fallback_failure_modes: list[str]) -> dict[str, Any]:
    update_type = _extract_string_field(text, "update_type")
    target_component = _extract_string_field(text, "target_component")
    suggested_change = _extract_string_field(text, "suggested_change")
    return {
        "failure_stage": _extract_string_field(text, "failure_stage") or "unknown",
        "failure_modes": fallback_failure_modes,
        "missed_evidence": [
            {"key": "evidence", "value": item}
            for item in _extract_list_field(text, "missed_evidence")
        ],
        "update_type": update_type,
        "target_component": target_component,
        "suggested_change": suggested_change,
        "rule_update_candidate": f"{target_component}: {suggested_change}".strip(": ").strip()
        if update_type == "rule" and suggested_change
        else "",
        "policy_update_candidate": f"{target_component}: {suggested_change}".strip(": ").strip()
        if update_type == "policy" and suggested_change
        else "",
        "prompt_update_candidate": f"{target_component}: {suggested_change}".strip(": ").strip()
        if update_type == "prompt" and suggested_change
        else "",
        "rationale": _extract_string_field(text, "rationale"),
    }


def _normalize_optional_text(value: Any) -> str:
    normalized = str(value or "").strip()
    if normalized.lower() in {"none", "null", "n/a", "na"}:
        return ""
    return normalized


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_normalize_optional_text(item) for item in value if _normalize_optional_text(item)]
    normalized = _normalize_optional_text(value)
    return [normalized] if normalized else []


def _normalize_reflection_output(parsed: dict[str, Any], fallback_failure_modes: list[str]) -> dict[str, Any]:
    missed = parsed.get("missed_evidence", [])
    normalized_missed: list[dict[str, str]] = []
    if isinstance(missed, list):
        for item in missed:
            if isinstance(item, dict):
                key = _normalize_optional_text(item.get("key"))
                value = _normalize_optional_text(item.get("value"))
                if key or value:
                    normalized_missed.append({"key": key or "evidence", "value": value})
            else:
                value = _normalize_optional_text(item)
                if value:
                    normalized_missed.append({"key": "evidence", "value": value})
    update_type = _normalize_optional_text(parsed.get("update_type"))
    if update_type not in {"rule", "policy", "prompt", "none"}:
        update_type = "none"
    target_component = _normalize_optional_text(parsed.get("target_component"))
    suggested_change = _normalize_optional_text(parsed.get("suggested_change"))
    combined_candidate = f"{target_component}: {suggested_change}".strip(": ").strip() if suggested_change else ""
    return {
        "failure_stage": _normalize_optional_text(parsed.get("failure_stage")) or "unknown",
        "failure_modes": _normalize_string_list(parsed.get("failure_modes")) or fallback_failure_modes,
        "missed_evidence": normalized_missed,
        "update_type": update_type,
        "target_component": target_component,
        "suggested_change": suggested_change,
        "rule_update_candidate": combined_candidate if update_type == "rule" else "",
        "policy_update_candidate": combined_candidate if update_type == "policy" else "",
        "prompt_update_candidate": combined_candidate if update_type == "prompt" else "",
        "rationale": _normalize_optional_text(parsed.get("rationale")),
    }


def _shorten_text(value: Any, limit: int = 280) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _compact_consultation_history(entries: list[dict[str, Any]]) -> list[dict[str, str]]:
    compact: list[dict[str, str]] = []
    for entry in entries[-3:]:
        if not isinstance(entry, dict):
            continue
        compact.append(
            {
                "department": _shorten_text(entry.get("department", ""), 60),
                "opinion": _shorten_text(entry.get("opinion", ""), 220),
            }
        )
    return compact


def _compact_decision_history(entries: list[dict[str, Any]]) -> list[dict[str, str]]:
    compact: list[dict[str, str]] = []
    for entry in entries[-5:]:
        if not isinstance(entry, dict):
            continue
        compact.append(
            {
                "actor": _shorten_text(entry.get("actor", ""), 40),
                "action": _shorten_text(entry.get("action", ""), 40),
                "rationale": _shorten_text(entry.get("rationale", ""), 180),
            }
        )
    return compact


def _compact_transcript_tail(entries: list[dict[str, Any]]) -> list[dict[str, str]]:
    compact: list[dict[str, str]] = []
    for entry in entries[-settings.OFFLINE_REFLECTION_MAX_TRANSCRIPT_ITEMS :]:
        if not isinstance(entry, dict):
            continue
        compact.append(
            {
                "role": _shorten_text(entry.get("role", ""), 40),
                "content": _shorten_text(entry.get("content", ""), 220),
            }
        )
    return compact


def _evidence_snapshot(reasoning_state: dict[str, Any]) -> dict[str, Any]:
    objective_findings = list(reasoning_state.get("objective_findings", []) or [])
    consultation_history = list(reasoning_state.get("consultation_history", []) or [])
    working_problem_list = list(reasoning_state.get("working_problem_list", []) or [])
    known_information = list(reasoning_state.get("known_information", []) or [])
    scores = infer_department_scores(
        [
            str(reasoning_state.get("er_working_diagnosis", "")).strip(),
            *(str(item).strip() for item in objective_findings if str(item).strip()),
            *(str(item.get("opinion", "")).strip() for item in consultation_history if isinstance(item, dict)),
            *(str(item).strip() for item in working_problem_list if str(item).strip()),
        ],
        prefer_clinical_department=True,
    )
    ranked_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:5]
    return {
        "working_problem_list": working_problem_list,
        "objective_findings": [_shorten_text(item, 220) for item in objective_findings[-5:]],
        "consultation_history": _compact_consultation_history(consultation_history),
        "known_information_tail": [_shorten_text(item, 180) for item in known_information[-6:]],
        "requested_tests": list(reasoning_state.get("requested_tests", []) or []),
        "requested_consults": list(reasoning_state.get("requested_consults", []) or []),
        "department_score_top5": ranked_scores,
    }


def build_false_case_rows(run_ids: Iterable[str] | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for run_id in _resolve_run_ids(run_ids):
        result_dir = settings.RESULTS_DIR / run_id
        log_dir = settings.LOGS_DIR / run_id
        transcript_dir = settings.TRANSCRIPTS_DIR / run_id
        if not result_dir.exists() or not log_dir.exists():
            continue

        for result_path in sorted(result_dir.glob("*_result.json")):
            result = _load_json(result_path)
            diagnosis_correct = result.get("diagnosis_correct") is True
            department_correct = result.get("department_correct")
            department_failure = department_correct is False
            if diagnosis_correct and not department_failure:
                continue

            case_id = str(result.get("case_id", "")).strip()
            reasoning_state_path = log_dir / f"{case_id}_reasoning_state.json"
            transcript_path = transcript_dir / f"{case_id}_transcript.json"
            if not reasoning_state_path.exists():
                continue

            reasoning_state = _load_json(reasoning_state_path)
            transcript = _load_json(transcript_path) if transcript_path.exists() else []

            failure_modes: list[str] = []
            if result.get("diagnosis_correct") is not True:
                failure_modes.append("diagnosis_false")
            if department_failure:
                failure_modes.append("department_false")

            row = {
                "run_id": run_id,
                "case_id": case_id,
                "failure_modes": failure_modes,
                "predicted_diagnosis": str(result.get("predicted_diagnosis", "")).strip(),
                "predicted_department": str(result.get("predicted_department", "")).strip(),
                "diagnostic_service": str(result.get("diagnostic_service", "")).strip(),
                "er_working_diagnosis": str(result.get("er_working_diagnosis", "")).strip(),
                "ground_truth_diagnosis": str(result.get("ground_truth", "")).strip(),
                "ground_truth_department": str(result.get("ground_truth_department", "")).strip(),
                "episode_reward": float(result.get("episode_reward", 0.0) or 0.0),
                "llm_call_count": int(reasoning_state.get("llm_call_count", 0) or 0),
                "reflection_count": int(reasoning_state.get("reflection_count", 0) or 0),
                "llm_self_reflection_count": int(reasoning_state.get("llm_self_reflection_count", 0) or 0),
                "decision_history_tail": _compact_decision_history(list(reasoning_state.get("decision_history", []) or [])),
                "evidence_snapshot": _evidence_snapshot(reasoning_state),
                "transcript_tail": _compact_transcript_tail(list(transcript or [])),
            }
            rows.append(row)

    if settings.OFFLINE_REFLECTION_MAX_FALSE_CASES > 0:
        rows = rows[: settings.OFFLINE_REFLECTION_MAX_FALSE_CASES]
    return rows


class OfflineFalseCaseReflectionRunner:
    def __init__(self) -> None:
        self.client = OllamaClient()
        self.system_prompt = load_prompt("offline_false_case_reflection_system.txt")
        if not self.system_prompt:
            raise ValueError(
                "Prompt file prompts/offline_false_case_reflection_system.txt is required for offline reflection."
            )

    def reflect_case(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "case_id": row["case_id"],
            "run_id": row["run_id"],
            "failure_modes": row["failure_modes"],
            "predicted_diagnosis": row["predicted_diagnosis"],
            "predicted_department": row["predicted_department"],
            "diagnostic_service": row["diagnostic_service"],
            "er_working_diagnosis": row["er_working_diagnosis"],
            "ground_truth_diagnosis": row["ground_truth_diagnosis"],
            "ground_truth_department": row["ground_truth_department"],
            "llm_call_count": row["llm_call_count"],
            "reflection_count": row["reflection_count"],
            "llm_self_reflection_count": row["llm_self_reflection_count"],
            "decision_history_tail": row["decision_history_tail"],
            "evidence_snapshot": row["evidence_snapshot"],
            "transcript_tail": row["transcript_tail"],
        }

        try:
            response = self.client.chat(
                self.system_prompt,
                json.dumps(payload, ensure_ascii=False, indent=2),
            ).strip()
            raw_json = _extract_json_object(response)
            try:
                parsed = json.loads(raw_json)
                parsed = _normalize_reflection_output(parsed, row["failure_modes"])
            except Exception:
                parsed = _fallback_parse_reflection_output(raw_json or response, row["failure_modes"])
                parsed = _normalize_reflection_output(parsed, row["failure_modes"])
        except Exception as exc:
            parsed = {
                "failure_stage": "unknown",
                "failure_modes": row["failure_modes"],
                "missed_evidence": [],
                "rule_update_candidate": "",
                "policy_update_candidate": "",
                "prompt_update_candidate": "",
                "rationale": f"Offline reflection failed to produce valid JSON: {exc}",
            }

        return {
            **row,
            "reflection": parsed,
        }


def summarize_reflections(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failure_mode_counts = Counter()
    stage_counts = Counter()
    rule_candidates = Counter()
    policy_candidates = Counter()
    prompt_candidates = Counter()
    update_type_counts = Counter()

    for row in rows:
        for mode in row.get("failure_modes", []):
            failure_mode_counts[mode] += 1
        reflection = row.get("reflection", {}) or {}
        stage = str(reflection.get("failure_stage", "")).strip()
        if stage:
            stage_counts[stage] += 1
        update_type = _normalize_optional_text(reflection.get("update_type", ""))
        if update_type:
            update_type_counts[update_type] += 1
        rule = _normalize_optional_text(reflection.get("rule_update_candidate", ""))
        if rule:
            rule_candidates[rule] += 1
        policy = _normalize_optional_text(reflection.get("policy_update_candidate", ""))
        if policy:
            policy_candidates[policy] += 1
        prompt = _normalize_optional_text(reflection.get("prompt_update_candidate", ""))
        if prompt:
            prompt_candidates[prompt] += 1

    return {
        "rows": len(rows),
        "failure_modes": dict(failure_mode_counts),
        "failure_stages": dict(stage_counts),
        "update_types": dict(update_type_counts),
        "top_rule_update_candidates": rule_candidates.most_common(10),
        "top_policy_update_candidates": policy_candidates.most_common(10),
        "top_prompt_update_candidates": prompt_candidates.most_common(10),
    }


def save_reflection_dataset(dataset_name: str, rows: list[dict[str, Any]], summary: dict[str, Any]) -> tuple[Path, Path]:
    settings.REFLECTIONS_DIR.mkdir(parents=True, exist_ok=True)
    jsonl_path = settings.REFLECTIONS_DIR / f"{dataset_name}.jsonl"
    summary_path = settings.REFLECTIONS_DIR / f"{dataset_name}_summary.json"

    with open(jsonl_path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    with open(summary_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)

    return jsonl_path, summary_path
