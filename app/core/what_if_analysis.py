from __future__ import annotations

from collections import defaultdict
from typing import Any


def _action_label(action: dict[str, Any]) -> str:
    if not isinstance(action, dict):
        return ""
    action_type = str(action.get("type", "")).strip()
    target = str(action.get("target", "")).strip()
    return f"{action_type}:{target}" if target else action_type


def analyze_what_if_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    total_cases = len(results)
    event_count = 0
    disagreement_count = 0
    cases_with_events = 0
    cases_with_disagreement = 0

    node_summary: dict[str, dict[str, int]] = defaultdict(lambda: {"events": 0, "disagreements": 0})
    transition_summary: dict[str, int] = defaultdict(int)
    false_case_events: list[dict[str, Any]] = []

    for result in results:
        case_id = str(result.get("case_id", "")).strip()
        diagnosis_correct = bool(result.get("diagnosis_correct"))
        department_correct = result.get("department_correct")
        events = list((result.get("reasoning_state", {}) or {}).get("what_if_shadow_events", []) or [])
        if events:
            cases_with_events += 1

        case_had_disagreement = False
        for event in events:
            node = str(event.get("node", "")).strip() or "unknown"
            proposed = event.get("proposed_action", {}) or {}
            selected = event.get("selected_action", {}) or {}
            proposed_label = _action_label(proposed)
            selected_label = _action_label(selected)

            event_count += 1
            node_summary[node]["events"] += 1

            disagreed = proposed_label != selected_label and bool(selected_label)
            if disagreed:
                disagreement_count += 1
                node_summary[node]["disagreements"] += 1
                transition_summary[f"{node}|{proposed_label}|{selected_label}"] += 1
                case_had_disagreement = True

            if (not diagnosis_correct) or (department_correct is False):
                false_case_events.append(
                    {
                        "case_id": case_id,
                        "node": node,
                        "turn_index": int(event.get("turn_index", 0) or 0),
                        "proposed_action": proposed,
                        "selected_action": selected,
                        "selection_rationale": str(event.get("selection_rationale", "")).strip(),
                        "diagnosis_correct": diagnosis_correct,
                        "department_correct": department_correct,
                    }
                )

        if case_had_disagreement:
            cases_with_disagreement += 1

    ranked_nodes = sorted(
        (
            {
                "node": node,
                "events": counts["events"],
                "disagreements": counts["disagreements"],
                "disagreement_rate": round(counts["disagreements"] / counts["events"], 4) if counts["events"] else 0.0,
            }
            for node, counts in node_summary.items()
        ),
        key=lambda item: (-item["disagreements"], -item["events"], item["node"]),
    )

    top_transitions = sorted(
        (
            {
                "node": key.split("|", 1)[0],
                "proposed_to_selected": key.split("|", 1)[1],
                "count": count,
            }
            for key, count in transition_summary.items()
        ),
        key=lambda item: (-item["count"], item["proposed_to_selected"]),
    )[:15]

    return {
        "total_cases": total_cases,
        "cases_with_events": cases_with_events,
        "cases_with_disagreement": cases_with_disagreement,
        "total_shadow_events": event_count,
        "total_shadow_disagreements": disagreement_count,
        "node_summary": ranked_nodes,
        "top_disagreement_transitions": top_transitions,
        "false_case_shadow_events": false_case_events[:100],
    }
