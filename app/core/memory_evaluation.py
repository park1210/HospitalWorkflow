"""Retrospective memory metrics. Annotations never enter model observations."""


def visit_key(identity):
    import json
    return json.dumps([identity["patient_id"], identity["visit_id"]], ensure_ascii=False)


def ratio(numerator, denominator, missing=False):
    return {"value": None if missing or not denominator else numerator / denominator,
            "numerator": None if missing else numerator, "denominator": None if missing else denominator,
            "status": "missing_annotation" if missing else "available" if denominator else "not_applicable"}


def validate_annotations(annotations):
    if not isinstance(annotations, dict):
        raise ValueError("Memory annotations must map visit keys to labels")
    for key, row in annotations.items():
        if not isinstance(key, str) or not isinstance(row, dict) or set(row) - {
                "relevant_memory_ids", "stale_memory_ids", "misused_memory_ids"}:
            raise ValueError("Invalid memory annotation fields")
        for values in row.values():
            if not isinstance(values, list) or any(not isinstance(x, str) or not x for x in values) or len(values) != len(set(values)):
                raise ValueError("Memory annotation IDs must be unique nonempty strings")
        if "misused_memory_ids" in row and not set(row["misused_memory_ids"]) <= set(row.get("stale_memory_ids", [])):
            raise ValueError("Misused stale memories must be a subset of stale_memory_ids")


def evaluate_memory(context, audit, annotation=None, eligible_ids=None):
    annotation = annotation or {}
    validate_annotations({"visit": annotation})
    if eligible_ids is not None:
        for field in ("relevant_memory_ids", "stale_memory_ids"):
            if not set(annotation.get(field, [])) <= set(eligible_ids):
                raise ValueError("Annotations reference unavailable, future or other-patient memory")
    selected = {r["memory_id"] for r in context.get("records", [])}
    relevant = set(annotation.get("relevant_memory_ids", []))
    stale = set(annotation.get("stale_memory_ids", []))
    cited = {key for a in audit if a.get("status") == "success"
             for key in a.get("memory_citations", {}).get("ids", [])}
    if not cited <= selected:
        raise ValueError("Citation outside provided memory")
    # Misuse requires external review; citing historical information is not
    # itself proof of accepting it as current fact.
    misused = set(annotation.get("misused_memory_ids", []))
    if not misused <= selected:
        raise ValueError("Misuse annotation references memory not shown in this run")
    return {"precision": ratio(len(selected & relevant), len(selected), "relevant_memory_ids" not in annotation),
            "recall": ratio(len(selected & relevant), len(relevant), "relevant_memory_ids" not in annotation),
            "stale_retrieval_rate": ratio(len(selected & stale), len(selected), "stale_memory_ids" not in annotation),
            "stale_misuse_rate": ratio(len(misused), len(selected & stale), "misused_memory_ids" not in annotation),
            "retrieved_ids": sorted(selected), "cited_ids": sorted(cited),
            "citation_reporting_complete": all(a.get("memory_citations", {}).get("reported", False)
                for a in audit if a.get("status") == "success" and a.get("role") != "patient"),
            "interpretation": "Citations are self-reported; semantic use and clinical correctness require review."}


def compare_memory_benefit(baseline, candidate, expected_diagnoses):
    """Paired observed accuracy difference, not a causal or significance test."""
    if baseline.get("mode") != "none" or candidate.get("mode") == "none":
        raise ValueError("Compare a no-memory baseline with a memory condition")
    signature = baseline.get("experiment_signature")
    if not signature or signature != candidate.get("experiment_signature"):
        raise ValueError("Cases, initial memory and non-memory experimental settings must match")
    left = {visit_key(v["identity"]): v for v in baseline["visits"]}
    right = {visit_key(v["identity"]): v for v in candidate["visits"]}
    if left.keys() != right.keys():
        raise ValueError("Paired visits must match")
    normalize = lambda s: " ".join(s.casefold().split())
    included, excluded = [], []
    for key, visit in left.items():
        labels = expected_diagnoses.get(key)
        if labels is None:
            excluded.append({"visit": key, "reason": "missing_diagnosis_labels"})
            continue
        if not isinstance(labels, list) or not labels or any(not isinstance(s, str) or not s.strip() for s in labels):
            raise ValueError("Expected diagnoses require explicit nonempty accepted labels")
        runtimes = [list(v["final_state"]["cases"].values()) for v in (visit, right[key])]
        if any(len(rows) != 1 for rows in runtimes):
            raise ValueError("Memory comparison requires single-visit states")
        states = [rows[0] for rows in runtimes]
        if not all(s["is_completed"] for s in states):
            excluded.append({"visit": key, "reason": "incomplete_visit"})
            continue
        scores = [int("diagnosis_unresolved" not in s["alerts"] and normalize(s["assessment_summary"]) in
                      {normalize(label) for label in labels}) for s in states]
        included.append({"visit": key, "baseline_correct": scores[0], "candidate_correct": scores[1],
                         "difference": scores[1] - scores[0]})
    observed = sum(r["difference"] for r in included) / len(included) if included else None
    return {"memory_benefit": observed if not excluded else None, "observed_subset_benefit": observed,
            "included": included, "excluded": excluded,
            "status": "missing_or_censored" if excluded else "available" if included else "not_applicable",
            "interpretation": "Closed-loop differences may include changed prior decisions; use fixed memory to isolate retrieval conditions."}
