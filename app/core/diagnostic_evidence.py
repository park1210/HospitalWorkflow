"""Evidence eligibility, separate from a model's diagnostic claim.

Only released objective findings qualify for the current supported-diagnosis
gate. Vital signs, history and opinions remain visible, but are not by
themselves a verified disease-specific diagnostic criterion.
"""
import math
import re


def informative(text):
    value = re.sub(r"[^\w\s]", "", str(text).casefold()).strip()
    value = " ".join(value.split())
    return bool(value) and value not in {
        "i am not sure about that", "i am not sure", "im not sure", "i dont know",
        "i do not know", "unknown", "unavailable", "not available", "not provided",
        "no information", "none", "null", "nan", "result unavailable in source data", "잘 모르겠습니다",
        "모르겠습니다", "모름", "알 수 없음",
    }


def diagnostic_evidence(runtime):
    records, excluded = [], []
    def add(source_id, kind, text, eligible=False):
        records.append({"source_id": source_id, "kind": kind, "text": str(text),
                        "supports_finalization": eligible})
    for index, text in enumerate(runtime.objective_findings):
        # A missing-result marker must not become evidence merely because it
        # is prefixed with a test name.
        result = str(text).split(":", 1)[-1]
        if informative(result):
            add(f"finding:{index}", "objective_finding", text, True)
        else:
            excluded.append({"source_id": f"finding:{index}", "reason": "unavailable_result"})
    for index, item in enumerate(runtime.question_history):
        answer = item.get("answer", "")
        if item.get("answer_status") == "unknown" or not informative(answer):
            excluded.append({"source_id": f"history:{index}", "reason": "unknown_answer"})
        else:
            add(f"history:{index}", "patient_history", answer)
    for name, value in runtime.vital_signs.items():
        try:
            number = float(value)
        except (ValueError, TypeError):
            continue
        if not isinstance(value, bool) and math.isfinite(number):
            add(f"vital:{name}", "vital_sign", f"{name}: {number:g}")
    for index, item in enumerate(runtime.consult_history):
        opinion = item.get("opinion", "")
        if informative(opinion):
            add(f"consult:{index}", "specialty_opinion", opinion)
    return records, excluded
