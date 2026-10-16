"""Chapter 5 retrospective evaluation of parallel runs. Never invokes a model.

Missing annotations and right-censoring remain explicit; no synthetic gold workflow.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from statistics import mean, median
from typing import Any, get_args

from app.core.event_schema import EventType
from app.core.physiology_profile import has_health_progression

from app.utils.department_catalog import normalize_department
from app.utils.diagnosis_catalog import canonicalize_diagnosis_text


ACTION_NAMES = {
    "ask_history": "ask_patient", "order_test": "request_test",
    "review_results": "review_result", "request_specialty": "consult_specialty",
    "er_finalize": "diagnose", "specialty_finalize": "diagnose",
    "reassessment": "reassessment",
}


def normalized(value: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", unicodedata.normalize("NFKC", value).casefold()).split())


def _strings(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
        raise ValueError(f"evaluation.{field} must be a list of nonempty strings")
    return value


def validate_evaluation(case: dict[str, Any]) -> None:
    evaluation = case.get("evaluation", {})
    if not isinstance(evaluation, dict):
        raise ValueError("evaluation must be an object")
    for name in ("critical_patient", "deterioration_at_risk"):
        if name in evaluation and not isinstance(evaluation[name], bool):
            raise ValueError(f"evaluation.{name} must be boolean")
    if "diagnosis_aliases" in evaluation:
        _strings(evaluation["diagnosis_aliases"], "diagnosis_aliases")
    workflow = evaluation.get("workflow", {})
    if not isinstance(workflow, dict):
        raise ValueError("evaluation.workflow must be an object")
    allowed = {"required_tests", "considered_tests", "acceptable_consultations", "critical_actions", "test_aliases"}
    if set(workflow) - allowed:
        raise ValueError("Unknown evaluation.workflow field")
    for field in ("required_tests", "considered_tests", "acceptable_consultations"):
        if field in workflow:
            _strings(workflow[field], field)
    for department in workflow.get("acceptable_consultations", []):
        if not normalize_department(department, default=""):
            raise ValueError(f"Unknown acceptable department: {department}")
    aliases = workflow.get("test_aliases", {})
    if not isinstance(aliases, dict) or any(not isinstance(k, str) or not normalized(k)
        or not isinstance(v, str) or not normalized(v) for k, v in aliases.items()):
        raise ValueError("test_aliases must map aliases to canonical names")
    normalized_aliases = {}
    for key, value in aliases.items():
        key, value = normalized(key), normalized(value)
        if key in normalized_aliases and normalized_aliases[key] != value:
            raise ValueError("Conflicting normalized test aliases")
        normalized_aliases[key] = value
    if any(value in normalized_aliases and normalized_aliases[value] != value for value in normalized_aliases.values()):
        raise ValueError("Test alias chains/cycles are not supported")
    actions = workflow.get("critical_actions", [])
    if not isinstance(actions, list):
        raise ValueError("critical_actions must be a list")
    ids = set()
    for action in actions:
        if not isinstance(action, dict) or set(action) - {"id", "event_type", "action", "target", "deadline_min"}:
            raise ValueError("Invalid critical action specification")
        for key in ("id", "event_type"):
            if not isinstance(action.get(key), str) or not action[key].strip():
                raise ValueError(f"Critical action requires {key}")
        if action["id"] in ids:
            raise ValueError("Critical action ids must be unique")
        if action["event_type"] not in get_args(EventType):
            raise ValueError("Critical action must reference an instrumented event type")
        ids.add(action["id"])
        for key in ("action", "target"):
            if key in action and (not isinstance(action[key], str) or not action[key].strip()):
                raise ValueError(f"Critical action {key} must be nonempty text")
        deadline = action.get("deadline_min")
        if deadline is not None and (isinstance(deadline, bool) or not isinstance(deadline, (int, float))
                                     or not math.isfinite(deadline) or deadline < 0):
            raise ValueError("Critical action deadline must be finite nonnegative minutes after arrival")


def _test_name(value: str, workflow: dict[str, Any]) -> str:
    aliases = {normalized(k): normalized(v) for k, v in workflow.get("test_aliases", {}).items()}
    return aliases.get(normalized(value), normalized(value))


def _quantile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * p
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def distribution(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "median": None, "q1": None, "q3": None, "iqr": None}
    q1, q3 = _quantile(values, 0.25), _quantile(values, 0.75)
    return {"n": len(values), "mean": mean(values), "median": median(values),
            "q1": q1, "q3": q3, "iqr": q3 - q1}


def _cell(value: Any = None, reason: str = "", numerator: int | None = None,
          denominator: int | None = None) -> dict[str, Any]:
    return {"value": value, "reason": reason, "numerator": numerator, "denominator": denominator}


def _ratio_cell(numerator: int, denominator: int) -> dict[str, Any]:
    return _cell(numerator / denominator if denominator else None,
                 "" if denominator else "zero_denominator", numerator, denominator)


def _critical_match(spec: dict[str, Any], event: dict[str, Any], arrival: int,
                    workflow: dict[str, Any]) -> bool:
    if event.get("event_type") != spec["event_type"]:
        return False
    if "action" in spec and event.get("action") != spec["action"]:
        return False
    if "deadline_min" in spec and event["minute"] - arrival > spec["deadline_min"]:
        return False
    if "target" not in spec:
        return True
    payload = event.get("payload", {})
    if "department" in payload:
        expected_department = normalize_department(spec["target"], default="")
        return bool(expected_department) and normalize_department(payload["department"], default="") == expected_department
    targets = [payload.get(k, "") for k in ("requested_test", "test_name", "department", "question")]
    expected = _test_name(spec["target"], workflow)
    return any(_test_name(str(t), workflow) == expected for t in targets if t)


def evaluate_case(runtime: Any, events: list[dict[str, Any]]) -> dict[str, Any]:
    case = runtime.case_data
    validate_evaluation(case)
    annotations = case.get("evaluation", {})
    workflow = annotations.get("workflow", {})
    gold = case.get("gold_label", {})
    # Event order disambiguates actions at the same minute as the final decision.
    trace = []
    finalized_event = False
    for event in events:
        trace.append(event)
        if event.get("event_type") == "case_completed":
            finalized_event = True
            break
    done = runtime.is_completed and runtime.final_diagnosis_min is not None
    complete_trace = done and finalized_event and any(e.get("event_type") in {"arrival_entered", "case_started"} for e in trace)
    cells = {}
    for name, field, predicted in (("diagnosis_accuracy", "diagnosis", runtime.assessment_summary),
                                    ("department_accuracy", "department", runtime.target_department)):
        expected = gold.get(field)
        if not isinstance(expected, str) or not expected.strip():
            cells[name] = _cell(reason="missing_gold_label")
        elif not done:
            cells[name] = _cell(reason="incomplete_case")
        elif "diagnosis_unresolved" in runtime.alerts:
            cells[name] = _ratio_cell(0, 1)
        elif field == "diagnosis":
            accepted = [expected, *annotations.get("diagnosis_aliases", [])]
            correct = any(canonicalize_diagnosis_text(predicted) == canonicalize_diagnosis_text(x) for x in accepted)
            cells[name] = _ratio_cell(int(correct), 1)
        else:
            target = normalize_department(expected, default="")
            cells[name] = (_ratio_cell(int(normalize_department(predicted, default="") == target), 1)
                           if target else _cell(reason="unknown_gold_department"))
    required = {_test_name(t, workflow) for t in workflow.get("required_tests", [])}
    performed = {_test_name(t, workflow) for t in runtime.completed_tests}
    completed_test_events = [e for e in trace if e.get("event_type") == "result_received"]
    observed_tests = [_test_name(str(e.get("payload", {}).get("requested_test", "")), workflow)
                      for e in completed_test_events]
    if "required_tests" not in workflow:
        cells["ntcr"] = cells["uti"] = _cell(reason="missing_required_tests")
    elif not done:
        cells["ntcr"] = cells["uti"] = _cell(reason="incomplete_case")
    else:
        cells["ntcr"] = _ratio_cell(len(required & performed), len(required))
        if "considered_tests" not in workflow:
            cells["uti"] = _cell(reason="missing_considered_tests")
        elif not complete_trace or any(not name for name in observed_tests):
            cells["uti"] = _cell(reason="incomplete_event_trace")
        else:
            acceptable = required | {_test_name(t, workflow) for t in workflow["considered_tests"]}
            cells["uti"] = _ratio_cell(sum(t not in acceptable for t in observed_tests), len(required))
    consults = [e for e in trace if e.get("event_type") == "consult_started"]
    if "acceptable_consultations" not in workflow:
        cells["ucr"] = _cell(reason="missing_acceptable_consultations")
    elif not complete_trace:
        cells["ucr"] = _cell(reason="incomplete_case_or_event_trace")
    else:
        acceptable = {normalize_department(d, default="") for d in workflow["acceptable_consultations"]}
        departments = [normalize_department(e.get("payload", {}).get("department", ""), default="") for e in consults]
        cells["ucr"] = (_ratio_cell(sum(d not in acceptable for d in departments), len(departments))
                        if all(departments) else _cell(reason="missing_consult_department"))
    missed = []
    if "critical_actions" not in workflow:
        cells["camr"] = _cell(reason="missing_critical_actions")
    elif not complete_trace:
        cells["camr"] = _cell(reason="incomplete_case_or_event_trace")
    else:
        for spec in workflow["critical_actions"]:
            if not any(_critical_match(spec, e, runtime.arrival_time_min, workflow) for e in trace[:-1]):
                missed.append(spec["id"])
        cells["camr"] = _ratio_cell(len(missed), len(workflow["critical_actions"]))
    action_counts = {}
    for event in trace:
        action = ACTION_NAMES.get(event.get("action"))
        if action:
            action_counts[action] = action_counts.get(action, 0) + 1
    cells["apl"] = _cell(sum(action_counts.values())) if complete_trace else _cell(reason="incomplete_case_or_event_trace")
    cells["ttd"] = (_cell(reason="unresolved_diagnosis") if "diagnosis_unresolved" in runtime.alerts else
                    _cell(runtime.final_diagnosis_min - runtime.arrival_time_min) if done else _cell(reason="incomplete_case"))
    cells["mwt"] = (_cell(runtime.first_evaluation_min - runtime.arrival_time_min)
                    if runtime.first_evaluation_min is not None else _cell(reason="not_evaluated"))
    critical = annotations.get("critical_patient")
    cells["cpwt"] = (_cell(reason="missing_critical_label") if critical is None else
                     cells["mwt"] if critical else _cell(reason="not_applicable"))
    at_risk = annotations.get("deterioration_at_risk")
    if at_risk is None:
        cells["dber"] = _cell(reason="missing_at_risk_label")
    elif not at_risk:
        cells["dber"] = _cell(reason="not_applicable")
    elif not has_health_progression(case):
        cells["dber"] = _cell(reason="missing_deterioration_model")
    elif runtime.first_evaluation_min is None:
        cells["dber"] = _cell(reason="not_evaluated")
    else:
        deteriorated = runtime.first_deterioration_min is not None and runtime.first_deterioration_min < runtime.first_evaluation_min
        cells["dber"] = _ratio_cell(int(deteriorated), 1)
    signature = hashlib.sha256(json.dumps(case, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return {"case_id": runtime.case_id, "case_signature": signature, "completed": done,
            "metrics": cells, "action_counts": action_counts, "missed_critical_action_ids": missed}


def evaluation_report(state: Any) -> dict[str, Any]:
    by_case = {cid: [] for cid in state.cases}
    for event in state.event_log:
        if event.get("case_id") in by_case:
            by_case[event["case_id"]].append(event)
    rows = [evaluate_case(c, by_case[cid]) for cid, c in state.cases.items()]
    categories = {"outcome": ("diagnosis_accuracy", "department_accuracy"),
                  "process": ("ntcr", "uti", "ucr"), "safety": ("camr",),
                  "efficiency": ("apl", "ttd"), "multi_patient": ("mwt", "cpwt", "dber")}
    groups = {}
    for group, names in categories.items():
        groups[group] = {}
        for name in names:
            cells = [(row["case_id"], row["metrics"][name]) for row in rows]
            excluded = [{"case_id": cid, "reason": c["reason"]} for cid, c in cells
                        if c["reason"] not in {"", "not_applicable", "zero_denominator"}]
            numeric = [c["value"] for _, c in cells if c["value"] is not None]
            numerator = sum(c["numerator"] or 0 for _, c in cells)
            denominator = sum(c["denominator"] or 0 for _, c in cells)
            is_distribution = name in {"apl", "ttd", "mwt", "cpwt"}
            observed = mean(numeric) if numeric else None
            if not is_distribution:
                observed = numerator / denominator if denominator else None
            status = "missing_or_censored" if excluded else "available" if observed is not None else "not_applicable"
            metric = {"value": observed if status == "available" else None,
                      "observed_value": observed, "status": status,
                      "included_cases": sum(c["value"] is not None or c["reason"] == "zero_denominator" for _, c in cells),
                      "total_cases": len(rows), "excluded": excluded,
                      "numerator": None if is_distribution else numerator,
                      "denominator": None if is_distribution else denominator}
            if is_distribution:
                metric["observed_distribution"] = distribution(numeric)
            groups[group][name] = metric
    return {"schema_version": 1, "run_id": state.run_id, "cohort_size": len(rows),
            "completed_count": sum(r["completed"] for r in rows), "groups": groups, "cases": rows,
            "validity": {"independent_clinical_evaluation": False,
                         "reason": ("llm_roles_separate_gold_but_dataset_and_clinical_validity_not_validated"
                                    if state.flow_config.get("clinical", {}).get("mode") == "llm_required"
                                    else "parallel_demo_policy_uses_gold_labels_and_may_synthesize_findings"),
                         "use": "simulation_audit_only",
                         "clinical_mode": state.flow_config.get("clinical", {}).get("mode", "demo")},
            "definitions": {"ntcr": "micro: sum unique required completed / sum unique required",
                "uti": "completed nonrecommended test events / required Perform tests; Consider excluded from numerator",
                "ucr": "nonacceptable actual consult starts / all consult starts; zero consultations is NA",
                "camr": "unmatched required critical actions before final event / required critical actions",
                "apl": "recorded clinical decision actions through final decision; movement and resource events excluded",
                "dber": "strictly earlier deterioration than first evaluation / independently labelled at-risk cases",
                "quantiles": "linear interpolation at (n-1)*p", "aggregate_score": "none"}}


def paired_comparison(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Within-case deltas; no unpaired averages or unsupported significance claims."""
    a = {r["case_id"]: r for r in left["cases"]}
    b = {r["case_id"]: r for r in right["cases"]}
    if not a or set(a) != set(b):
        raise ValueError("Paired reports require identical nonempty case sets")
    if any(a[cid]["case_signature"] != b[cid]["case_signature"] for cid in a):
        raise ValueError("Paired reports require identical cases, arrivals and annotations")
    if left.get("schema_version") != right.get("schema_version") or left.get("definitions") != right.get("definitions"):
        raise ValueError("Paired metric definitions must match")
    result = {}
    for name in next(iter(a.values()))["metrics"]:
        deltas, excluded = {}, []
        for cid in a:
            x, y = a[cid]["metrics"][name]["value"], b[cid]["metrics"][name]["value"]
            if x is None or y is None:
                excluded.append(cid)
            else:
                deltas[cid] = y - x
        result[name] = {"right_minus_left_by_case": deltas,
                        "delta_distribution": distribution(list(deltas.values())), "excluded_case_ids": excluded}
    return {"metrics": result, "interpretation": "paired_case_deltas_not_micro_aggregate_differences_or_significance_test",
            "independent_clinical_evaluation": False}
