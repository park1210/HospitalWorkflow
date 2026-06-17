from __future__ import annotations

from typing import Any

from app.utils.clinical_rule_loader import load_department_ownership_rules


def _count_markers(evidence_text: str) -> dict[str, int]:
    return {
        "renal_markers": sum(
            1
            for marker in [
                "urinalysis",
                "urine sediment",
                "creatinine",
                "proteinuria",
                "hematuria",
                "albuminuria",
                "nephrotic",
                "nephritic",
                "eosinophil",
                "eosinophilic",
                "hansel",
                "interstitial nephritis",
            ]
            if marker in evidence_text
        ),
        "renal_primary_markers": sum(
            1
            for marker in [
                "proteinuria",
                "hematuria",
                "albuminuria",
                "nephrotic",
                "nephritic",
                "eosinophil",
                "eosinophilic",
                "hansel",
                "interstitial nephritis",
            ]
            if marker in evidence_text
        ),
        "structural_markers": sum(
            1
            for marker in ["fracture", "dislocation", "joint effusion", "tendon", "ligament", "osseous", "hip", "spine", "vertebra"]
            if marker in evidence_text
        ),
        "gynecologic_markers": sum(
            1
            for marker in ["pregnan", "adnexal", "ovarian", "uterine", "pelvic ultrasound", "vaginal bleeding"]
            if marker in evidence_text
        ),
        "breast_structural_markers": sum(
            1
            for marker in ["breast mass", "breast", "stromal", "leaf-like", "polylobulated", "biopsy", "mammography"]
            if marker in evidence_text
        ),
        "infectious_markers": sum(
            1
            for marker in ["fever", "infection", "antibiotic", "bacter", "pus", "abscess", "cellulitis"]
            if marker in evidence_text
        ),
        "disseminated_gonococcal_markers": sum(
            1
            for marker in ["gonorrhea", "gram-negative diplococci", "joint aspiration", "vesiculopustular", "sexually active"]
            if marker in evidence_text
        ),
        "tuberculosis_markers": sum(
            1
            for marker in ["chronic cough", "night sweats", "weight loss", "released from prison", "prison", "diffuse infiltrates", "tuberculin", "crackles"]
            if marker in evidence_text
        ),
    }


def apply_department_ownership_overrides(score_map: dict[str, float], evidence_text: str) -> tuple[dict[str, float], list[str]]:
    scores = dict(score_map)
    normalized_text = str(evidence_text or "").strip().lower()
    override_notes: list[str] = []
    if not normalized_text:
        return scores, override_notes

    marker_counts = _count_markers(normalized_text)

    for rule in load_department_ownership_rules():
        keyword_groups = rule.get("keyword_groups", []) or []
        min_groups = int(rule.get("min_groups", len(keyword_groups) or 1))
        matched_groups = 0
        for group in keyword_groups:
            group_items = [str(item).lower() for item in group if str(item).strip()]
            if group_items and any(item in normalized_text for item in group_items):
                matched_groups += 1
        if matched_groups < min_groups:
            continue

        min_thresholds = {str(key): int(value) for key, value in (rule.get("min_marker_thresholds", {}) or {}).items()}
        max_thresholds = {str(key): int(value) for key, value in (rule.get("max_marker_thresholds", {}) or {}).items()}
        if any(marker_counts.get(name, 0) < value for name, value in min_thresholds.items()):
            continue
        if any(marker_counts.get(name, 0) > value for name, value in max_thresholds.items()):
            continue

        department = str(rule.get("department", "")).strip()
        min_score = float(rule.get("min_score", 0.0) or 0.0)
        note = str(rule.get("note", "")).strip()
        if department and min_score > 0:
            scores[department] = max(scores.get(department, 0.0), min_score)
        if note and note not in override_notes:
            override_notes.append(note)

    if marker_counts["renal_markers"] >= 3 and marker_counts["renal_primary_markers"] >= 2:
        scores["nephrology"] = max(scores.get("nephrology", 0.0), 8.0)
        override_notes.append("nephrology override: multiple renal-primary objective markers")

    if any(marker in normalized_text for marker in ["x-ray", "xray", "ct", "mri", "ultrasound", "imaging"]) and marker_counts["structural_markers"] >= 2:
        scores["orthopedics"] = max(scores.get("orthopedics", 0.0), 7.5)
        override_notes.append("orthopedics override: structural imaging with fracture/dislocation/tendon-ligament pattern")

    if marker_counts["gynecologic_markers"] >= 2:
        scores["obstetrics_gynecology"] = max(scores.get("obstetrics_gynecology", 0.0), 7.5)
        override_notes.append("obstetrics_gynecology override: pregnancy or gynecologic imaging/bleeding evidence")

    return scores, override_notes
