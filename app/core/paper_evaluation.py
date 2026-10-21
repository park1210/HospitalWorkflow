"""Patient-paired descriptive statistics; failed visits remain in denominators."""
import random
from app.core.memory_evaluation import visit_key


def mean(values):
    return sum(values) / len(values) if values else None


def episode_rows(cases, labels, report, condition, repeat, gold_departments=None):
    saved = {visit_key(v["identity"]): v for v in (report or {}).get("visits", [])}
    rows = []
    for case in cases:
        identity = case["longitudinal"]
        key = visit_key(identity)
        visit = saved.get(key)
        state = next(iter(visit["final_state"]["cases"].values())) if visit else None
        complete = bool(state and state["is_completed"])
        label = labels[key]
        accepted = label if isinstance(label, list) else [label]
        normalize = lambda s: " ".join(s.casefold().split())
        correct = bool(complete and "diagnosis_unresolved" not in state["alerts"] and
                       normalize(state["assessment_summary"]) in {normalize(x) for x in accepted})
        audit = state.get("llm_audit", []) if state else []
        trace = state.get("voi_state", {}).get("history", []) if state else []
        selected = [r for r in trace if r.get("status") == "selected"]
        decisions = [r["decision"] for r in audit if r.get("decision") and r.get("status") == "success"]
        # Encounter decisions already include the VoI override in the LLM audit.
        # Counting the planning trace again doubles B4's executed action count.
        if "index_encounter_id" not in case:
            decisions += [{"action": r["selected_action"], "rationale": r.get("rationale", "")} for r in selected]
        # Historical reports lacking decision logs cannot support action-count claims.
        logging_complete = all(r.get("decision") for r in audit if r.get("status") == "success" and r.get("role") != "patient")
        gains = [next((c["information_gain_nats"] for c in r.get("candidates", []) if c["action_id"] == r.get("action_id")), None)
                 for r in selected if r.get("action_id")]
        metrics = visit.get("memory_evaluation", {}) if visit else {}
        gold = (gold_departments or {}).get(key)
        consults = state.get("consult_history", []) if state else []
        row = {"condition": condition, "repeat": repeat, "patient_id": identity["patient_id"], "visit_id": identity["visit_id"],
               "completed": int(complete), "correct_all_planned": int(correct), "correct_completed": int(correct) if complete else None,
               "visit_status": "completed" if complete else "failed_or_incomplete" if visit else "not_run",
               "llm_calls": len(audit) if state else None,
               "failed_calls": sum(r.get("status") == "error" for r in audit) if state else None,
               "timeout_calls": sum("timeout" in r.get("error_type", "").casefold() for r in audit) if state else None,
               "tokens": sum(r["usage"]["total_tokens"] for r in audit) if state and all(r.get("usage") for r in audit) else None,
               "llm_latency_seconds": sum(r["latency_seconds"] for r in audit) if state and all(r.get("latency_seconds") is not None for r in audit) else None,
               "actions": len(decisions) if state and logging_complete else None,
               "rationales_missing": sum(not d.get("rationale", "").strip() for d in decisions) if state else None,
               "tests": len(state["completed_tests"]) if state else None,
               "consults": len(state["consult_history"]) if state else None,
               "questions": len(state["question_history"]) if state else None,
               "completion_minutes": state["final_diagnosis_min"] if complete else None,
               "consult_department_precision": mean([int(c["department"] in gold) for c in consults]) if gold is not None and consults else None,
               "final_department_accuracy": int(state["target_department"] in gold) if gold is not None and complete else None,
               "expected_ig_nats": sum(gains) if gains and all(g is not None for g in gains) else None}
        for name in ("precision", "recall", "stale_retrieval_rate", "stale_misuse_rate"):
            row["memory_" + name] = metrics.get(name, {}).get("value")
        rows.append(row)
    return rows


def aggregate(rows):
    result = []
    for condition in sorted({r["condition"] for r in rows}):
        group = [r for r in rows if r["condition"] == condition]
        row = {"condition": condition, "planned_visit_runs": len(group), "patients": len({r["patient_id"] for r in group})}
        for metric in ("completed", "correct_all_planned", "correct_completed", "llm_calls", "failed_calls", "timeout_calls", "tokens", "llm_latency_seconds", "actions", "tests", "consults",
                       "questions", "completion_minutes", "consult_department_precision", "final_department_accuracy", "expected_ig_nats", "memory_precision", "memory_recall", "memory_stale_retrieval_rate", "memory_stale_misuse_rate"):
            values = [r[metric] for r in group if r[metric] is not None]
            row[metric] = mean(values)
            row[metric + "_coverage"] = len(values) / len(group)
        result.append(row)
    return result


def paired(rows, left, right, metric, samples=2000, seed=42):
    groups = {c: {(r["repeat"], r["patient_id"], r["visit_id"]): r for r in rows if r["condition"] == c} for c in (left, right)}
    keys = set(groups[left]) | set(groups[right])
    patients = {}
    missing = 0
    for key in sorted(keys):
        a, b = groups[left].get(key), groups[right].get(key)
        if a is None or b is None or a[metric] is None or b[metric] is None:
            missing += 1
            continue
        patients.setdefault(key[1], []).append(b[metric] - a[metric])
    # Average visits and repeats within patient, then bootstrap patients, not rows.
    values = [mean(v) for v in patients.values()]
    result = {"baseline": left, "candidate": right, "metric": metric, "patients": len(values),
              "missing_pairs": missing, "difference": mean(values) if not missing else None,
              "observed_subset_difference": mean(values), "ci95": None,
              "estimand": "equally weighted patient means; candidate minus baseline"}
    if len(values) >= 2 and not missing:
        rng = random.Random(seed)
        draws = sorted(mean(rng.choices(values, k=len(values))) for _ in range(samples))
        result["ci95"] = [draws[int(.025 * (samples - 1))], draws[int(.975 * (samples - 1))]]
    return result
