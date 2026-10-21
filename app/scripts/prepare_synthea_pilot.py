"""Adapt and validate the existing JSONL; optional pre-model boundary smoke only."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from app.data.synthea_adapter import convert_case, validate_case, EVALUATION_KEYS


class ModelBoundary:
    """Stop at the actual role_call boundary, before network/model execution."""
    def __init__(self):
        self.trace = None

    def chat_json(self, system, prompt, model=None, schema=None):
        payload = json.loads(prompt)
        observation = payload["observation"]
        from app.core.clinical_observation import memory_query
        for forbidden in EVALUATION_KEYS:
            if forbidden in json.dumps(observation) or forbidden in memory_query(observation):
                raise AssertionError("Evaluation metadata leaked to model projection")
        self.trace = {
            "role": payload["role"], "model_binding": model, "network_calls": 0,
            "observed_keys": sorted(observation),
            "initial_vitals": observation["vital_signs"],
            "memory_count": len(observation.get("longitudinal_memory", {}).get("records", [])),
            "memory_ids": [r["memory_id"] for r in observation.get("longitudinal_memory", {}).get("records", [])],
            "memory_query": memory_query(observation),
            "routing": payload.get("routing_context"),
            "candidate_actions": payload["candidate_actions"],
            "payload_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "prompt_characters": len(prompt), "status": "stopped_before_model_call"}
        raise RuntimeError("Intentional offline boundary; no LLM called")


def offline_registry():
    from app.utils.department_catalog import SUPPORTED_DEPARTMENTS
    # Independent of case annotations. These are deliberately non-runnable model bindings.
    return {"schema_version": 1, "agents": [
        {"agent_id": "offline-er", "role": "er", "department": "", "model": "OFFLINE_UNBOUND",
         "version": "adapter-boundary-only", "keywords": []},
        *[{"agent_id": "offline-" + d, "role": "specialty", "department": d,
           "model": "OFFLINE_UNBOUND", "version": "adapter-boundary-only",
           "keywords": [d.replace("_", " ")]} for d in SUPPORTED_DEPARTMENTS]]}


def smoke(cases):
    from app.core.longitudinal_runner import run_longitudinal
    chosen = [next(c for c in cases if c["primary_specialty"] == d)
              for d in ("cardiology", "pulmonology", "surgery")]
    traces = []
    for mode in ("none", "full_history", "selective"):
        for case in chosen:
            boundary = ModelBoundary()
            report = run_longitudinal([case], mode=mode, top_k=1, minute_limit=120,
                                     memory_source="fixed", registry_manifest=offline_registry(),
                                     routing_mode="adaptive", client=boundary,
                                     action_selector="specialist_heuristic")
            if boundary.trace is None or boundary.trace["role"] != "specialty":
                raise AssertionError("Did not reach specialist model boundary")
            runtime = next(iter(report["visits"][0]["final_state"]["cases"].values()))
            trace = {**boundary.trace, "case_id": case["case_id"], "memory_mode": mode,
                     "runner_status": report["status"], "expected_boundary_exception": True,
                     "failure_detail": report["visits"][0].get("failure_detail")}
            assert runtime["llm_audit"][-1]["backend"] == "ModelBoundary"
            assert report["status"] == "failed"  # intentional client sentinel, not clinical failure
            traces.append(trace)
            print(mode, case["case_id"], "boundary reached", trace["memory_count"], flush=True)
    return {"case_count": 3, "runs": 9, "actual_llm_calls": 0, "traces": traces}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, default=Path("pilot_base_cases.jsonl"))
    p.add_argument("--output", type=Path, default=Path("app/data/synthea_pilot_encounters.json"))
    p.add_argument("--smoke", action="store_true")
    args = p.parse_args()
    if args.source.resolve() == args.output.resolve() or args.output.exists():
        raise ValueError("Choose a new output; source and existing outputs are never overwritten")
    raw = args.source.read_bytes()
    fingerprint = hashlib.sha256(raw).hexdigest()
    rows = [json.loads(line) for line in raw.decode("utf-8-sig").splitlines() if line.strip()]
    if len(rows) != 15 or len({r["case_id"] for r in rows}) != 15:
        raise ValueError("Expected 15 unique pilot cases")
    schema = {"source": str(args.source), "sha256": fingerprint, "cases": len(rows),
              "fields": dict(Counter(k for r in rows for k in r)),
              "specialties": dict(Counter(r["primary_specialty"] for r in rows)),
              "current_types": dict(Counter(e["event_type"] for r in rows for e in r["current_encounter_events"])),
              "current_precision": dict(Counter(e["time_precision"] for r in rows for e in r["current_encounter_events"])),
              "past_visits": sum(len(r["past_visits"]) for r in rows),
              "past_events": sum(len(v["events"]) for r in rows for v in r["past_visits"])}
    Path("synthea_pilot_schema_analysis.md").write_text(
        "# Synthea pilot 실제 스키마 분석\n\n"
        "요청 이름은 `pilot_base_cases(1).jsonl`이나 접근 가능한 실제 파일은 프로젝트 최상위의 "
        "`pilot_base_cases.jsonl`이다. 두 파일의 동일성은 확인되지 않았다. 실제 읽은 파일의 hash를 기록한다.\n\n"
        "모든 15개 case에 아래 13개 필드가 존재한다. demographics, chief_complaint, "
        "current_initial_state는 원본에 없다. task_eligibility/annotation_metadata는 평가용이다.\n\n"
        "past_visits: encounter_id/start_time/stop_time/encounter_class/code/description/events.\n\n"
        "event: event_id/event_type/event_time/time_precision/data/source_file/source_row_number.\n\n"
        "events의 observations는 description/value/units/category/code 등을 담고, procedures는 수행 기록이며 "
        "정상/비정상 판독문을 보장하지 않는다. imaging_studies는 영상 획득 메타데이터다. "
        "원본에 Ask/Consult 형태의 환자 응답이나 전문의 의견은 없다.\n\n"
        "```json\n" + json.dumps(schema, ensure_ascii=False, indent=2) + "\n```\n", encoding="utf-8")
    converted = []
    for row in rows:
        case = convert_case(row, args.source.name, fingerprint)
        validate_case(row, case)
        converted.append(case)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(converted, f, ensure_ascii=False, separators=(",", ":"))
    validation = {**schema, "converted_cases": len(converted),
                  "past_runtime_records": sum(len(v["records"]) for c in converted for v in c["past_visits"]),
                  "runtime_events": sum(len(c["current_encounter_events"]) for c in converted),
                  "initial_vitals_cases": sum(bool(c["initial_state_source_event_ids"]) for c in converted),
                  "event_dispositions": dict(Counter(m["disposition"] for c in converted for m in c["source_event_metadata"].values())),
                  "checks": ["unique_case_ids", "patient_and_encounter_match", "past_cutoff",
                             "initial_projection_no_annotation_fields", "source_event_lineage",
                             "nonnegative_relative_minutes", "raw_history_preserved", "source_sha256_unchanged"]}
    out = Path("outputs/synthea_pilot_adapter")
    out.mkdir(parents=True, exist_ok=True)
    if args.smoke:
        trace = smoke(converted)
        (out / "offline_smoke.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    assert hashlib.sha256(args.source.read_bytes()).hexdigest() == fingerprint
    validation["source_unchanged"] = True
    (out / "validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(validation, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
