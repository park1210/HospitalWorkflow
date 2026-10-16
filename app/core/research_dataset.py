"""Patient-split research bundles with explicit synthetic/review provenance."""
from copy import deepcopy
from app.core.longitudinal_memory import PatientMemoryStore, visit_identity
from app.core.memory_evaluation import evaluate_memory, validate_annotations, visit_key


def validate_bundle(bundle):
    if bundle.get("schema_version") != 1 or bundle.get("provenance", {}).get("review_status") not in {"unreviewed", "expert_reviewed"}:
        raise ValueError("Dataset needs explicit review provenance")
    provenance = bundle["provenance"]
    if type(provenance.get("synthetic")) is not bool:
        raise ValueError("Declare whether data are synthetic")
    if provenance["review_status"] == "expert_reviewed" and not all(provenance.get(k) for k in ("reviewer", "review_reference")):
        raise ValueError("Expert review requires reviewer and review reference")
    owners = {}
    if set(bundle["splits"]) != {"train", "validation", "test"}:
        raise ValueError("Require patient-level train/validation/test splits")
    for split, patients in bundle["splits"].items():
        for patient in patients:
            if patient in owners:
                raise ValueError("Patient crosses splits or appears twice")
            owners[patient] = split
    store = PatientMemoryStore(bundle["memory"]["records"])
    if bundle["memory"].get("schema_version") != 1:
        raise ValueError("Unsupported memory schema")
    validate_annotations(bundle["annotations"])
    keys = set()
    for case in bundle["cases"]:
        identity = visit_identity(case)
        key = visit_key(identity)
        if identity["patient_id"] not in owners or key in keys:
            raise ValueError("Unassigned patient or duplicate visit")
        keys.add(key)
        eligible = store.retrieve(identity, "", "full_history")["records"]
        labels = bundle["annotations"].get(key)
        if labels is None or "relevant_memory_ids" not in labels or "stale_memory_ids" not in labels:
            raise ValueError("Every visit needs relevance/staleness labels")
        if "misused_memory_ids" in labels:
            raise ValueError("Misuse must be annotated after a specific run, not in the source dataset")
        evaluate_memory({}, [], labels, [r["memory_id"] for r in eligible])
        diagnoses = bundle["expected_diagnoses"].get(key)
        if not isinstance(diagnoses, list) or not diagnoses or any(not isinstance(s, str) or not s.strip() for s in diagnoses):
            raise ValueError("Missing accepted diagnosis labels")
    if set(bundle["annotations"]) != keys or set(bundle["expected_diagnoses"]) != keys:
        raise ValueError("Labels and visits must match exactly")
    if any(r["patient_id"] not in owners for r in bundle["memory"]["records"]):
        raise ValueError("Memory patient absent from splits")
    return {"patients": len(owners), "visits": len(keys), "records": len(bundle["memory"]["records"]),
            "clinical_validation": provenance["review_status"], "synthetic": provenance["synthetic"]}


def synthetic_bundle(template):
    cases, records, annotations, diagnoses = [], [], {}, {}
    splits = {"train": [], "validation": [], "test": []}
    for index in range(6):
        patient = f"synthetic-patient-{index}"
        splits[("train", "validation", "test")[index // 2]].append(patient)
        for j, text in enumerate(("Patient reports synthetic discomfort", "Patient denies synthetic discomfort")):
            when = "2025-12-01T00:00:00Z" if j == 0 else "2026-01-15T00:00:00Z"
            records.append({"memory_id": f"{patient}-memory-{j}", "patient_id": patient, "visit_id": f"prior-{j}",
                            "visit_started_at": when, "observed_at": when, "available_at": when,
                            "source_id": "synthetic-generator-v1", "kind": "history", "text": text, "supersedes": []})
        for j, original in enumerate(template):
            case = deepcopy(original)
            case["case_id"] = f"{patient}-visit-{j}"
            case["longitudinal"]["patient_id"] = patient
            cases.append(case)
            key = visit_key(visit_identity(case))
            annotations[key] = {"relevant_memory_ids": [f"{patient}-memory-{min(j, 1)}"],
                                "stale_memory_ids": [f"{patient}-memory-0"] if j else []}
            diagnoses[key] = ["Synthetic unresolved condition"]
    bundle = {"schema_version": 1, "provenance": {"synthetic": True, "review_status": "unreviewed",
              "label_source": "generator rules; not clinical ground truth"}, "splits": splits,
              "cases": cases, "memory": {"schema_version": 1, "records": records},
              "annotations": annotations, "expected_diagnoses": diagnoses}
    validate_bundle(bundle)
    return bundle
