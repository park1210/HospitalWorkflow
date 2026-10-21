"""One visit at a time: isolate memory effects from hospital crowding."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json

from app.core.hospital_parallel_scheduler import HospitalParallelScheduler
from app.core.longitudinal_memory import PatientMemoryStore, timestamp, visit_identity
from app.core.agent_registry import AgentRegistry
from app.core.memory_evaluation import evaluate_memory, validate_annotations, visit_key
from app.core.memory_retrieval import MemoryEmbeddings
from app.llm.role_call import RoleCallError
from app.config import settings
from app.core.call_costs import summarize_costs
from app.core.information_value import InformationPolicy
from app.core.clinical_observation import doctor_observation, prepare_encounter, memory_query


def run_longitudinal(cases, *, mode="none", top_k=5, minute_limit=120, client=None,
                     registry_manifest=None, routing_mode="llm", routing_seed=0,
                     initial_memory=None, memory_source="closed_loop", memory_annotations=None,
                     max_memory_chars=None, embedding_artifact=None, routing_utility=None,
                     resume_report=None, checkpoint_callback=None, token_prices=None, voi_model=None, diagnosis_catalog=None,
                     action_selector=None, primary_router="rule_similarity"):
    if primary_router not in {"rule_similarity", "adaptive", "llm", "memory_aware_llm"}:
        raise ValueError("Unknown primary router")
    if diagnosis_catalog is not None and (not isinstance(diagnosis_catalog, list) or not diagnosis_catalog
            or any(not isinstance(d, str) or not d.strip() or len(d) > 240 for d in diagnosis_catalog)
            or len(set(diagnosis_catalog)) != len(diagnosis_catalog)):
        raise ValueError("Diagnosis catalog must be unique nonempty labels of at most 240 characters")
    cases = [prepare_encounter(case) for case in cases]
    if initial_memory is None and any("index_encounter_id" in c for c in cases):
        initial_memory = []
    encounter_records = [r for c in cases for v in c.get("past_visits", []) for r in v["records"]]
    if encounter_records:
        merged = {r["memory_id"]: r for r in initial_memory or []}
        for record in encounter_records:
            if record["memory_id"] in merged and merged[record["memory_id"]] != record:
                raise ValueError("Conflicting memory copies across encounters")
            merged[record["memory_id"]] = record
        initial_memory = list(merged.values())
    if any("index_encounter_id" in c for c in cases) and registry_manifest is None:
        raise ValueError("Encounter routing requires an explicit agent registry")
    summarize_costs([], token_prices or {})
    action_selector = action_selector or ("bayesian_voi" if voi_model is not None else "specialist_heuristic")
    if action_selector not in {"bayesian_voi", "information_gain", "specialist_heuristic", "random"}:
        raise ValueError("Unknown action selector")
    information_policy = InformationPolicy(voi_model, action_selector) if (
        voi_model is not None and action_selector in {"bayesian_voi", "information_gain"}) else None
    if memory_source not in {"closed_loop", "fixed"} or (memory_source == "fixed" and initial_memory is None):
        raise ValueError("Fixed-memory experiments require an explicit initial memory artifact")
    annotations = deepcopy(memory_annotations or {})
    validate_annotations(annotations)
    embeddings = MemoryEmbeddings(embedding_artifact) if embedding_artifact is not None else None
    if mode == "semantic" and embeddings is None:
        raise ValueError("Semantic mode needs an embedding artifact")
    registry = AgentRegistry(registry_manifest, routing_utility) if registry_manifest is not None else None
    if routing_utility is not None and registry is None:
        raise ValueError("Utility requires registry")
    if registry is None and routing_mode != "llm":
        raise ValueError("Routing baselines require an explicit agent registry")
    if registry is not None:
        registry.route({}, [], mode=routing_mode, seed=routing_seed)
    routing_config = {"mode": routing_mode, "primary_router": primary_router, "seed": routing_seed,
                      "utility_sha256": registry.utility.fingerprint if registry and registry.utility else None,
                      "registry": registry.snapshot() if registry else None}
    if isinstance(minute_limit, bool) or not isinstance(minute_limit, int) or minute_limit < 1:
        raise ValueError("minute_limit must be positive")
    if mode not in {"none", "full_history", "selective", "summary", "semantic"}:
        raise ValueError("Invalid memory mode")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
        raise ValueError("top_k must be positive")
    visits = [(visit_identity(case), deepcopy(case)) for case in cases]
    if information_policy and any(i["patient_id"] in voi_model["provenance"].get("training_patients", []) for i, _ in visits):
        raise ValueError("Evaluation patients overlap VoI training patients")
    if registry and registry.utility and any(i["patient_id"] in registry.utility.training_patients for i, _ in visits):
        raise ValueError("Evaluation patients overlap routing training patients")
    ids = [(i["patient_id"], i["visit_id"]) for i, _ in visits]
    starts = [(i["patient_id"], timestamp(i["started_at"])) for i, _ in visits]
    if len(set(ids)) != len(ids) or len(set(starts)) != len(starts):
        raise ValueError("Duplicate visit ID or simultaneous visits for one patient")
    visits.sort(key=lambda pair: (timestamp(pair[0]["started_at"]), pair[0]["patient_id"], pair[0]["visit_id"]))
    store, results, completed_at = PatientMemoryStore(initial_memory or []), [], {}
    if set(annotations) - {visit_key(i) for i, _ in visits}:
        raise ValueError("Annotations contain a visit not present in this experiment")
    model_config = {key: getattr(settings, key) for key in (
        "OLLAMA_MODEL", "SPECIALTY_OLLAMA_MODEL", "TEMPERATURE", "LLM_TIMEOUT_SECONDS", "LLM_MAX_OUTPUT_TOKENS")}
    contract = {"cases": cases, "initial_memory": initial_memory, "memory_source": memory_source,
                "routing": routing_config, "minute_limit": minute_limit, "model_config": model_config,
                "token_prices": token_prices}
    contract["voi_model_sha256"] = information_policy.model.fingerprint if information_policy else None
    contract["diagnosis_catalog"] = diagnosis_catalog
    # Do not resume old paid visits under a changed action/grounding contract.
    contract["clinical_policy_revision"] = "adaptive-primary-executable-multistep-v5"
    contract["action_selector"] = action_selector
    experiment_signature = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()
    retrieval_config = {"top_k": top_k, "max_chars": max_memory_chars,
                        "embedding_sha256": embeddings.fingerprint if embeddings else None}
    resume_signature = hashlib.sha256(json.dumps([experiment_signature, mode, retrieval_config, annotations], sort_keys=True).encode()).hexdigest()
    comparison_contract = {k: v for k, v in contract.items() if k != "voi_model_sha256"}
    voi_comparison_signature = hashlib.sha256(json.dumps([comparison_contract, mode, retrieval_config], sort_keys=True).encode()).hexdigest()
    committed_count = 0
    discarded_attempts = []
    if resume_report is not None:
        signed = {k: v for k, v in resume_report.items() if k != "checkpoint_digest"}
        if resume_report.get("checkpoint_digest") != hashlib.sha256(json.dumps(signed, sort_keys=True).encode()).hexdigest():
            raise ValueError("Checkpoint integrity check failed")
        if resume_report.get("resume_signature") != resume_signature:
            raise ValueError("Resume settings/data do not match checkpoint")
        committed_count = resume_report["committed_count"]
        if type(committed_count) is not int or not 0 <= committed_count <= len(visits):
            raise ValueError("Invalid checkpoint visit count")
        results = deepcopy(resume_report["visits"][:committed_count])
        if len(results) != committed_count:
            raise ValueError("Truncated checkpoint")
        store = PatientMemoryStore(resume_report["memory"]["records"])
        discarded_attempts = deepcopy(resume_report.get("discarded_attempts", []))
        discarded_attempts.extend(deepcopy(resume_report["visits"][committed_count:]))
        for n, saved in enumerate(results):
            if saved["identity"] != visits[n][0]:
                raise ValueError("Checkpoint visit order mismatch")
            rows = list(saved["final_state"]["cases"].values())
            if len(rows) != 1 or not rows[0]["is_completed"]:
                raise ValueError("Checkpoint contains uncommitted visit")
            completed_at[saved["identity"]["patient_id"]] = timestamp(saved["identity"]["started_at"]) + timedelta(minutes=rows[0]["final_diagnosis_min"])
    def report(status):
        audit = [a for v in results + discarded_attempts for runtime in v["final_state"]["cases"].values()
                 for a in runtime.get("llm_audit", [])]
        payload = {"status": status, "mode": mode, "memory_source": memory_source,
                "voi_model": deepcopy(voi_model), "voi_model_sha256": contract["voi_model_sha256"],
                "voi_comparison_signature": voi_comparison_signature,
                "call_costs": summarize_costs(audit, token_prices or {}),
                "resume_signature": resume_signature, "committed_count": committed_count,
                "discarded_attempts": discarded_attempts,
                "experiment_signature": experiment_signature, "routing_config": routing_config,
                "model_config": model_config,
                "diagnosis_catalog": deepcopy(diagnosis_catalog),
                "retrieval_config": retrieval_config,
                "visits": results, "memory": store.snapshot(),
                "limitations": ["retrieval scores and citations are not clinical correctness",
                                 "contextual utility and VoI models require held-out clinical validation",
                                 "objective-evidence termination gate retained across all modes"]}
        payload["checkpoint_digest"] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        return deepcopy(payload)
    # Validate update containers before spending model calls; temporal validation
    # depends on the actual visit completion time.
    for identity, case in visits:
        updates = case.get("longitudinal", {}).get("memory_updates", [])
        if memory_source == "fixed" and updates:
            raise ValueError("Fixed mode requires all updates in the initial memory artifact")
        if not isinstance(updates, list):
            raise ValueError("memory_updates must be a list")
    for identity, case in visits[committed_count:]:
        if timestamp(identity["started_at"]) < completed_at.get(identity["patient_id"], timestamp(identity["started_at"])):
            raise ValueError("Overlapping visits for the same patient")
        scheduler = HospitalParallelScheduler({"clinical": {"mode": "llm_required"}}, llm_client=client)
        scheduler.clinical_policy.agent_registry = registry
        scheduler.clinical_policy.routing_mode = routing_mode
        scheduler.clinical_policy.primary_router_mode = primary_router
        scheduler.clinical_policy.routing_seed = routing_seed
        scheduler.clinical_policy.information_policy = information_policy
        scheduler.clinical_policy.action_selector = action_selector
        scheduler.clinical_policy.diagnosis_catalog = diagnosis_catalog
        # The visit horizon must constrain choices, not just stop the scheduler
        # while an avoidable late consultation is still running.
        scheduler.clinical_policy.decision_deadline_minute = minute_limit
        scheduler.clinical_policy.flow_durations = dict(scheduler.config["durations"])
        # Each visit has its own local simulation clock and no other patients.
        case.setdefault("temporal_profile", {})["arrival_time_min"] = 0
        state = scheduler.initialize([case])
        runtime = state.case(case["case_id"])
        if "synthea_v2_patient_input" in case:
            runtime.objective_findings.extend(case.get("synthea_v2_initial_evidence", []))
        query = str(case.get("doctor_visible_info", {}).get("chief_complaint", ""))
        if "index_encounter_id" in case:
            query = memory_query(doctor_observation(runtime))
            def refresh_memory(rt, observed, identity=identity):
                return store.retrieve(identity, memory_query(observed), mode, top_k,
                                      max_chars=max_memory_chars, embeddings=embeddings)
            scheduler.clinical_policy.memory_retriever = refresh_memory
        runtime.memory_context = store.retrieve(identity, query, mode, top_k,
                                               max_chars=max_memory_chars, embeddings=embeddings)
        if ("index_encounter_id" not in case and information_policy
                and any(a["type"] == "retrieve_memory" for a in voi_model["actions"])):
            runtime.voi_memory_pool = deepcopy(runtime.memory_context)
            runtime.memory_context = {"mode": "none", "records": []}
        eligible = store.retrieve(identity, query, "full_history")["records"]
        annotation = annotations.get(visit_key(identity), {})
        evaluate_memory(runtime.memory_context, [], {k: v for k, v in annotation.items() if k != "misused_memory_ids"},
                        [r["memory_id"] for r in eligible])
        failed = None
        try:
            scheduler.run_until(state, minute_limit)
        except RoleCallError as exc:
            failed = type(exc).__name__
        if information_policy:
            try:
                final_belief, final_matched = information_policy.model.observe(doctor_observation(runtime))
                runtime.voi_state.update(belief=final_belief, matched_outcomes=final_matched, belief_status="valid")
            except ValueError:
                runtime.voi_state["belief_status"] = "unsupported_observation"
        memory_audit = runtime.llm_audit + [{**r, "status": "success", "role": "er"}
            for r in runtime.voi_state.get("history", []) if "memory_citations" in r]
        results.append({"identity": identity, "memory_context": deepcopy(runtime.memory_context),
                        "eligible_memory_ids": [r["memory_id"] for r in eligible],
                        "memory_evaluation": evaluate_memory(runtime.memory_context, memory_audit, annotation,
                                                            [r["memory_id"] for r in eligible]),
                        "final_state": state.snapshot()})
        if failed:
            results[-1]["error_type"] = failed
            results[-1]["stop_reason"] = "role_call_failed"
            last_error = next((a for a in reversed(runtime.llm_audit)
                               if a.get("status") == "error"), {})
            results[-1]["failure_detail"] = {key: last_error[key] for key in
                ("role", "error_type", "failure_category", "validation_error", "validation_detail",
                 "response_sha256", "repair_of_audit_index") if key in last_error}
            return report("failed")
        if not runtime.is_completed:
            results[-1]["stop_reason"] = "visit_minute_limit_reached"
            results[-1]["stop_detail"] = {
                "minute_limit": minute_limit, "current_minute": state.current_minute,
                "workflow_state": runtime.workflow_state,
                "pending_results_count": runtime.pending_results_count,
                "consult_count": len(runtime.consult_history),
            }
            return report("incomplete")
        if memory_source == "closed_loop":
            next_store = PatientMemoryStore(store.snapshot()["records"])
            next_store.ingest_completed_visit(runtime)
            end = timestamp(identity["started_at"]) + timedelta(minutes=runtime.final_diagnosis_min)
            for update in case.get("longitudinal", {}).get("memory_updates", []):
                if (update.get("patient_id") != identity["patient_id"] or update.get("visit_id") != identity["visit_id"]
                    or timestamp(update["visit_started_at"]) != timestamp(identity["started_at"])
                    or timestamp(update["available_at"]) > end):
                    raise ValueError("Visit updates must belong to this patient/visit and be available by completion")
                next_store.add(update)
            store = next_store
        completed_at[identity["patient_id"]] = timestamp(identity["started_at"]) + timedelta(minutes=runtime.final_diagnosis_min)
        committed_count += 1
        if checkpoint_callback:
            checkpoint_callback(report("checkpoint"))
    return report("completed")


def run_with_recovery(cases, *, max_retries=0, **kwargs):
    """Retry only the uncommitted visit from its start; retain paid failed attempts."""
    if type(max_retries) is not int or not 0 <= max_retries <= 3:
        raise ValueError("max_retries must be between 0 and 3")
    for attempt in range(max_retries + 1):
        result = run_longitudinal(cases, **kwargs)
        if kwargs.get("checkpoint_callback"):
            kwargs["checkpoint_callback"](result)
        if result["status"] != "failed" or attempt == max_retries:
            return result
        kwargs["resume_report"] = result
