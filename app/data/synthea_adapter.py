"""Source-preserving adapter only; no clinical inference or outcome model fitting."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
import re

VERSION = "v1"
VITALS = {"8480-6": "sbp", "8462-4": "dbp", "8867-4": "hr", "9279-1": "rr",
          "8310-5": "temperature", "59408-5": "spo2", "2708-6": "spo2"}
DIAGNOSTIC = re.compile(r"assessment|examination|imaging|scan|radiograph|x-ray|echocardi|"
                        r"electrocardio|mammogra|biopsy|testing|screening|culture|ultrasound|"
                        r"magnetic resonance|computed tomography", re.I)
EVALUATION_KEYS = {"primary_specialty", "acceptable_specialties", "gold_condition_code",
                   "gold_condition_description", "annotation_metadata", "task_eligibility"}


def instant(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise ValueError("Exact timestamps require timezone")
    return result.astimezone(timezone.utc)


def serialized(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def safe_data(event, cutoff=None):
    """Keep source values verbatim; remove annotations/reasons and future-valued dates."""
    result = {}
    for key, value in event["data"].items():
        if key in EVALUATION_KEYS or key.startswith(("gold_", "reason")):
            continue
        if cutoff is not None and key in {"stop", "end", "date", "start"} and value:
            try:
                when = instant(value) if "T" in value else datetime.fromisoformat(value).replace(tzinfo=timezone.utc) + timedelta(days=1)
                if when > cutoff:
                    continue
            except (ValueError, TypeError):
                continue
        result[key] = value
    return result


def convert_case(source, filename, fingerprint):
    required = {"case_id", "patient_id", "index_encounter_id", "index_encounter_start",
                "index_encounter_class", "past_visits", "current_encounter_events", *EVALUATION_KEYS}
    if not required <= set(source):
        raise ValueError("Missing source fields: " + str(required - set(source)))
    cutoff = instant(source["index_encounter_start"])
    result = {k: deepcopy(source[k]) for k in ("case_id", "index_encounter_id", "index_encounter_start",
              "primary_specialty", "acceptable_specialties", "task_eligibility", "annotation_metadata")}
    result["longitudinal"] = {"patient_id": source["patient_id"]}
    result["evaluation"] = {k: source[k] for k in ("gold_condition_code", "gold_condition_description")}
    result["source_provenance"] = {"source": filename, "source_sha256": fingerprint,
                                  "synthea": True, "adapter_version": VERSION}
    # Preserve all source history/events outside the model projection, including excluded events.
    result["source_past_visits"] = deepcopy(source["past_visits"])
    result["source_current_encounter_events"] = deepcopy(source["current_encounter_events"])
    result["source_event_metadata"], result["past_record_metadata"] = {}, {}
    result["data_limitation"] = ["No source demographics or explicit initial chief complaint.",
        "Event timestamps are recording times, not proven result-availability times.",
        "No counterfactual outcome probabilities; Bayesian VoI unavailable.",
        "Procedure/imaging occurrence is not an interpreted clinical result."]
    result["conversion_exclusions"] = []
    result["past_visits"] = []
    for visit in source["past_visits"]:
        if instant(visit["start_time"]) >= cutoff or visit["encounter_id"] == source["index_encounter_id"]:
            raise ValueError("Past visit is not before index encounter")
        if visit.get("patient_id", source["patient_id"]) != source["patient_id"]:
            raise ValueError("Cross-patient visit")
        converted = {"visit_id": visit["encounter_id"], "started_at": visit["start_time"], "records": []}
        for event in visit["events"]:
            if event.get("patient_id", source["patient_id"]) != source["patient_id"]:
                raise ValueError("Cross-patient event")
            if event["time_precision"] == "date":
                # An availability upper bound, NOT an inferred event occurrence minute.
                available = datetime.fromisoformat(event["event_time"]).replace(tzinfo=timezone.utc) + timedelta(days=1)
                observed = available
                policy = "date_upper_bound_next_midnight_not_occurrence_time"
            elif event["time_precision"] == "datetime":
                observed = available = instant(event["event_time"])
                policy = "source_timestamp"
            else:
                result["conversion_exclusions"].append({"event_id": event["event_id"], "reason": "unknown_past_time_precision"})
                continue
            if available > cutoff or observed < instant(visit["start_time"]):
                result["conversion_exclusions"].append({"event_id": event["event_id"], "reason": "past_time_boundary"})
                continue
            memory_id = source["patient_id"] + ":" + event["event_id"]
            data = safe_data(event, cutoff)
            kind = "objective_finding" if event["event_type"] == "observations" else (
                "prior_assessment" if event["event_type"] == "conditions" else "history")
            converted["records"].append({
                "memory_id": memory_id, "patient_id": source["patient_id"], "visit_id": visit["encounter_id"],
                "visit_started_at": visit["start_time"], "observed_at": observed.isoformat(),
                "available_at": available.isoformat(), "source_id": event["event_id"],
                "kind": kind, "text": serialized(data), "supersedes": []})
            result["past_record_metadata"][memory_id] = {
                "event_id": event["event_id"], "timestamp": event["event_time"],
                "timing_precision": event["time_precision"], "availability_policy": policy,
                "removed_fields": sorted(set(event["data"]) - set(data))}
        result["past_visits"].append(converted)
    initial = {"arrival_info": source["index_encounter_class"]}
    vital_sources, vitals = [], {}
    intervened = any(e["event_type"] in {"medications", "procedures"} and e["time_precision"] == "datetime"
                     and instant(e["event_time"]) <= cutoff for e in source["current_encounter_events"])
    result["current_encounter_events"] = []
    for event in source["current_encounter_events"]:
        if event.get("patient_id", source["patient_id"]) != source["patient_id"]:
            raise ValueError("Cross-patient current event")
        data = safe_data(event)
        metadata = {"timestamp": event["event_time"], "timing_precision": event["time_precision"],
                    "source_type": event["event_type"], "source_code": data.get("code", data.get("procedure_code")),
                    "source_description": data.get("description", data.get("modality_description")),
                    "source_file": event["source_file"], "source_row_number": event["source_row_number"]}
        result["source_event_metadata"][event["event_id"]] = metadata
        if event["time_precision"] != "datetime":
            metadata.update(available_minute=None, disposition="preserved_only", reason="date_only_order_unknown")
            continue
        when = instant(event["event_time"])
        if when < cutoff:
            metadata.update(available_minute=None, disposition="preserved_only", reason="before_index")
            continue
        if (not intervened and when == cutoff and event["event_type"] == "observations"
                and data.get("category") == "vital-signs" and data.get("code") in VITALS):
            try:
                value = float(data["value"])
                if math.isfinite(value):
                    vitals[VITALS[data["code"]]] = value
                    vital_sources.append(event["event_id"])
                    metadata["disposition"] = "initial_vital"
                    continue
            except (ValueError, KeyError):
                pass
        allowed = (event["event_type"] == "observations" and "value" in data
                   or event["event_type"] == "imaging_studies"
                   or event["event_type"] == "procedures" and DIAGNOSTIC.search(data.get("description", "")))
        if not allowed:
            metadata.update(disposition="preserved_only", reason="not_supported_information_action")
            continue
        # A procedure occurrence becomes knowable no earlier than documented completion.
        release = max(when, instant(data["stop"])) if data.get("stop") and "T" in data["stop"] else when
        minute = math.ceil((release - cutoff).total_seconds() / 60)
        description = data.get("description", data.get("modality_description", event["event_type"]))
        # Disambiguate repeat observations without including result values or gold.
        target = f"{description} [{event['event_id']}]"
        if len(target) > 240:
            target = f"{description[:190]} [{event['event_id']}]"
        result["current_encounter_events"].append({
            "event_id": event["event_id"], "action": "Test", "target": target,
            "available_minute": minute, "evidence": serialized(data)})
        metadata.update(available_minute=minute, disposition="Test", release_timestamp=release.isoformat(),
                        rounding="ceil_to_existing_integer_clock", removed_fields=sorted(set(event["data"]) - set(data)))
    if vitals:
        initial["initial_vitals"] = vitals
    result["current_initial_state"] = {"doctor_visible_info": initial, "patient_visible_info": {}}
    result["initial_state_source_event_ids"] = vital_sources
    if intervened:
        result["data_limitation"].append("Same-time intervention order unknown; no initial vital inference.")
    if not vitals:
        result["data_limitation"].append("Initial clinical findings unavailable; encounter class alone is not a routing diagnosis.")
    return result


def validate_case(source, result):
    """Validate content lineage independently of future model calls."""
    from app.core.clinical_observation import prepare_encounter
    assert result["case_id"] == source["case_id"]
    assert result["longitudinal"]["patient_id"] == source["patient_id"]
    assert result["index_encounter_id"] == source["index_encounter_id"]
    assert result["index_encounter_start"] == source["index_encounter_start"]
    assert result["source_past_visits"] == source["past_visits"]
    assert result["source_current_encounter_events"] == source["current_encounter_events"]
    assert not any(k in serialized(result["current_initial_state"]) for k in EVALUATION_KEYS)
    lookup = {e["event_id"]: e for e in source["current_encounter_events"]}
    for event in result["current_encounter_events"]:
        original = lookup[event["event_id"]]
        assert event["evidence"] == serialized(safe_data(original))
        assert event["available_minute"] >= 0
        assert original["time_precision"] == "datetime"
        assert event["available_minute"] * 60 >= (instant(original["event_time"]) - instant(source["index_encounter_start"])).total_seconds()
    for event_id in result["initial_state_source_event_ids"]:
        original = lookup[event_id]
        assert original["event_time"] == source["index_encounter_start"]
        assert original["event_type"] == "observations"
        assert original["data"]["code"] in VITALS
    prepare_encounter(result)
