"""Conservative assertion/negation candidates, never automatic clinical overwrite."""
import re


def assertion(text):
    text = " ".join(text.casefold().strip().rstrip(".! ").split())
    # Deliberately full-match narrow grammar: do not infer negation scope in prose.
    patterns = [(r"(?:patient )?(?:denies|does not have|has no) ([\w -]+)", False),
                (r"(?:patient )?(?:reports|has) ([\w -]+)", True),
                (r"([\w -]+)\s*:\s*(present|absent)", None),
                (r"([\w가-힣 -]+)\s+(있음|없음)", None)]
    for pattern, positive in patterns:
        match = re.fullmatch(pattern, text)
        if match:
            entity = match[1].strip()
            if any(w in entity.split() for w in ("and", "or", "but", "not", "no", "history", "family")):
                return None
            return entity, positive if positive is not None else match[2] in {"present", "있음"}
    return None


def detect_conflicts(records):
    results = []
    for i, left in enumerate(records):
        a = assertion(left["text"])
        if not a or left.get("status_as_of_visit") == "superseded":
            continue
        for right in records[i + 1:]:
            b = assertion(right["text"])
            if (b and a[0] == b[0] and a[1] != b[1] and left["patient_id"] == right["patient_id"]
                    and right.get("status_as_of_visit") != "superseded"):
                results.append({"memory_ids": [left["memory_id"], right["memory_id"]], "entity": a[0],
                                "status": "requires_review", "rule": "opposite_explicit_polarity",
                                "rationale": "Opposite assertions may reflect temporal change; preserve both sources and verify current state."})
    return results
