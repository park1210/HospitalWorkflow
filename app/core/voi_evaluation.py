"""Offline probability calibration and paired VoI-policy evaluation."""
from copy import deepcopy
import math
from app.core.information_outcomes import InformationOutcomes
from app.core.memory_evaluation import visit_key


def fit_outcomes(template, rows, alpha=1.0):
    model = InformationOutcomes(template)
    if type(alpha) not in (float, int) or not math.isfinite(alpha) or alpha <= 0:
        raise ValueError("Smoothing alpha must be positive")
    artifact = deepcopy(model.artifact)
    diagnoses = artifact["diagnoses"]
    actions = {a["id"]: a for a in artifact["actions"]}
    cases, seen, patients = {}, set(), set()
    counts = {key: {o["id"]: {d: alpha for d in diagnoses} for o in a["outcomes"]} for key, a in actions.items()}
    for row in rows:
        if row["split"] != "train" or row["diagnosis"] not in diagnoses:
            raise ValueError("Fit only train-split outcomes with known diagnosis labels")
        if any(not isinstance(row[k], str) or not row[k] for k in ("patient_id", "visit_id")):
            raise ValueError("Patient/visit IDs required")
        case = (row["patient_id"], row["visit_id"])
        key, result, diagnosis = row["action_id"], row["outcome_id"], row["diagnosis"]
        if (case, key) in seen or (case in cases and cases[case] != diagnosis):
            raise ValueError("Duplicate outcome or inconsistent visit diagnosis")
        if key not in counts or result not in counts[key]:
            raise ValueError("Unknown action/outcome")
        seen.add((case, key))
        cases[case] = diagnosis
        patients.add(row["patient_id"])
        counts[key][result][diagnosis] += 1
    if not cases:
        raise ValueError("No training data")
    artifact["prior"] = {d: (alpha + sum(y == d for y in cases.values())) / (alpha * len(diagnoses) + len(cases)) for d in diagnoses}
    for key, action in actions.items():
        for outcome in action["outcomes"]:
            outcome["likelihood"] = {d: counts[key][outcome["id"]][d] / sum(r[d] for r in counts[key].values()) for d in diagnoses}
    artifact["provenance"].update(review_status="unreviewed", fit_method="dirichlet_counts_v1", smoothing_alpha=alpha,
                                  training_patients=sorted(patients), training_visits=len(cases), training_rows=len(rows))
    artifact["revision"] += ":fitted"
    InformationOutcomes(artifact)
    return artifact


def evaluate_voi(report, labels):
    model = InformationOutcomes(report["voi_model"]) if report.get("voi_model") else None
    rows, calibration = [], []
    known_keys = {visit_key(v["identity"]) for v in report["visits"]}
    if set(labels) - known_keys:
        raise ValueError("Labels contain visits outside report")
    for visit in report["visits"]:
        key = visit_key(visit["identity"])
        if model and visit["identity"]["patient_id"] in model.artifact["provenance"].get("training_patients", []):
            raise ValueError("VoI evaluation patients overlap training")
        states = list(visit["final_state"]["cases"].values())
        if len(states) != 1:
            raise ValueError("Single-visit states required")
        state = states[0]
        label = labels.get(key)
        if label is not None and (not isinstance(label, str) or not label.strip()):
            raise ValueError("VoI labels must be one canonical diagnosis string per visit")
        if label is not None and model and label not in model.artifact["diagnoses"]:
            raise ValueError("Truth outside the model's diagnosis universe")
        trace = state.get("voi_state", {})
        belief = trace.get("belief") if trace.get("belief_status") == "valid" else None
        complete = state["is_completed"]
        correct = ("diagnosis_unresolved" not in state["alerts"] and state["assessment_summary"].casefold().strip() == label.casefold().strip()) if label and complete else None
        audit = state.get("llm_audit", [])
        selected = [r for r in trace.get("history", []) if r.get("status") == "selected"]
        row = {"visit": key, "completed": complete, "correct": correct, "belief": belief,
               "llm_calls": len(audit), "tests": len(state["completed_tests"]), "questions": len(state["question_history"]),
               "consults": len(state["consult_history"]), "completion_minutes": state["final_diagnosis_min"],
               "modeled_action_cost": sum(r.get("cost_penalty", 0) for r in selected),
               "fallback_decisions": sum(r.get("status") == "fallback" for r in trace.get("history", [])),
               "brier": None, "log_loss": None}
        if belief and label and complete:
            row["brier"] = sum((p - int(d == label)) ** 2 for d, p in belief.items())
            row["log_loss"] = -math.log(belief[label]) if belief[label] > 0 else None
            row["zero_probability_truth"] = belief[label] == 0
            predicted = min(belief, key=lambda d: (-belief[d], d))
            calibration.append((belief[predicted], int(predicted == label)))
        rows.append(row)
    scored = [r for r in rows if r["correct"] is not None]
    brier_rows = [r for r in rows if r["brier"] is not None]
    log_rows = [r for r in rows if r["log_loss"] is not None]
    bins = []
    for index in range(10):
        values = [v for v in calibration if min(int(v[0] * 10), 9) == index]
        if values:
            confidence = sum(v[0] for v in values) / len(values)
            accuracy = sum(v[1] for v in values) / len(values)
            bins.append({"lower": index / 10, "count": len(values), "confidence": confidence, "accuracy": accuracy})
    return {"visits": rows, "accuracy": sum(r["correct"] for r in scored) / len(scored) if scored and len(scored) == len(rows) else None,
            "accuracy_coverage": len(scored) / len(rows) if rows else None,
            "calibration_bins": bins, "ece": sum(b["count"] * abs(b["confidence"] - b["accuracy"]) for b in bins) / len(calibration) if calibration else None,
            "calibration_cases": len(calibration), "calibration_coverage": len(calibration) / len(rows) if rows else None,
            "mean_brier": sum(r["brier"] for r in brier_rows) / len(brier_rows) if brier_rows and len(brier_rows) == len(rows) else None,
            "mean_log_loss": sum(r["log_loss"] for r in log_rows) / len(log_rows) if log_rows and len(log_rows) == len(rows) else None,
            "zero_probability_truth_count": sum(r.get("zero_probability_truth", False) for r in rows),
            "interpretation": "Model-based finite-universe scores; clinical validation and coverage review required."}


def compare_voi(baseline, candidate, labels):
    if baseline.get("voi_model") is not None or candidate.get("voi_model") is None:
        raise ValueError("Compare a no-VoI baseline with a VoI candidate")
    if not baseline.get("voi_comparison_signature") or baseline["voi_comparison_signature"] != candidate.get("voi_comparison_signature"):
        raise ValueError("Cases, memory, routing, budgets and model settings must match")
    left, right = evaluate_voi(baseline, labels), evaluate_voi(candidate, labels)
    if {v["visit"] for v in left["visits"]} != {v["visit"] for v in right["visits"]}:
        raise ValueError("Paired visits must match")
    delta = right["accuracy"] - left["accuracy"] if left["accuracy"] is not None and right["accuracy"] is not None else None
    return {"baseline": left, "candidate": right, "accuracy_difference": delta,
            "llm_call_difference": sum(v["llm_calls"] for v in right["visits"]) - sum(v["llm_calls"] for v in left["visits"]),
            "baseline_all_attempt_costs": baseline.get("call_costs"), "candidate_all_attempt_costs": candidate.get("call_costs"),
            "interpretation": "Call difference covers retained visits; all-attempt cost summaries also include discarded retries. No causal/significance claim."}
