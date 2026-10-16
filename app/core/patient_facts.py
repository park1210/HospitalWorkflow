"""Extractive patient speech: the model selects facts, never supplies new prose."""
import json
import re


def patient_facts(observation):
    facts = []
    def add(key, text, scope):
        text = str(text).strip()
        if text:
            facts.append({"id": key, "text": text, "scope": scope})
    for index, symptom in enumerate(observation.get("current_symptoms", [])):
        add(f"current:{index}", f"My current symptoms include: {symptom}.", "current")
    for field in ("history", "past_medical_history", "current_medications", "medications", "allergies", "social_history"):
        value = observation.get(field)
        if isinstance(value, str):
            for index, sentence in enumerate(re.split(r"(?<=[.!?])\s+", value)):
                add(f"{field}:{index}", sentence, "history")
    # Static callers without a runtime still have their original symptom facts.
    if "current_symptoms" not in observation:
        add("complaint:0", observation.get("chief_complaint", ""), "current")
    return facts


def selection_schema(facts):
    return {"type": "object", "properties": {
        "fact_ids": {"type": "array", "maxItems": 3 if facts else 0,
                     "items": {"type": "string", "enum": [f["id"] for f in facts] or ["unavailable"]}},
        "unknown": {"type": "boolean", **({"enum": [True]} if not facts else {})}},
        "required": ["fact_ids", "unknown"], "additionalProperties": False}


def facts_for_question(facts, question):
    """Conservative topic filter; absence of a matching fact means unknown."""
    q = question.casefold()
    if re.search(r"\b(when|how long|onset|start|started|since)\b|언제|시작|얼마나 오래", q):
        time_words = r"\b(started|began|ago|today|yesterday|since|after|before|morning|evening|days?|weeks?|months?|years?|minutes?|hours?)\b|오늘|어제|시작|전부터"
        return [f for f in facts if f["id"].startswith("history:") and re.search(time_words, f["text"], re.IGNORECASE)]
    for pattern, fields in ((r"\b(medications?|medicines?|drugs?|taking)\b|복용|약물", ("medications:", "current_medications:")),
                            (r"\b(allergies|allergy|allergic)\b|알레르기", ("allergies:",)),
                            (r"past medical|medical history|과거력|기저질환", ("past_medical_history:",))):
        if re.search(pattern, q):
            return [f for f in facts if f["id"].startswith(fields)]
    if re.search(r"\b(now|currently|right now)\b|지금|현재", q):
        return [f for f in facts if f["scope"] == "current"]
    return facts


def render_selection(raw, facts):
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {"fact_ids", "unknown"}:
        raise ValueError("Patient response requires only fact_ids and unknown; free prose is not accepted")
    ids = value["fact_ids"]
    available = {f["id"]: f["text"] for f in facts}
    if (not isinstance(ids, list) or len(ids) > 3 or any(not isinstance(i, str) or i not in available for i in ids)
            or len(set(ids)) != len(ids) or type(value["unknown"]) is not bool):
        raise ValueError("Invalid patient fact selection")
    if value["unknown"]:
        if ids:
            raise ValueError("Unknown response must not assert facts")
        return "I am not sure about that."
    if not ids:
        raise ValueError("A factual response needs at least one source fact")
    return " ".join(available[i] for i in ids)
