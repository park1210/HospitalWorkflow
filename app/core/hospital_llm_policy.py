"""Evidence-only LLM role policy for the parallel scheduler.

The simulator owns results/time/resources; models choose one validated action.
Demo gold labels and unreleased results never enter model observations.
"""
import hashlib
import json
from copy import deepcopy

from app.agents.patient_agent import PatientAgent
from app.config import settings
from app.core.clinical_observation import doctor_observation, encounter_evidence, memory_query
from app.core.information_value import candidate_actions, select_action
from app.core.diagnostic_belief import DiagnosisBelief
from app.core.diagnostic_evidence import diagnostic_evidence
from app.core.clinical_followup import available_consult_departments
from app.core.hospital_specialty_policy import HospitalSpecialtyPolicy
from app.core.hospital_test_model import test_timing
from app.llm.ollama_client import OllamaClient
from app.llm.role_call import role_call, RoleCallError, ContractValidationError
from app.core.specialty_router import LLMRouter
from app.utils.department_catalog import (
    normalize_department,
    SUPPORTED_DEPARTMENTS,
    DEPARTMENT_ALIASES,
    canonicalize_department_text,
)
from app.llm.prompt_loader import (
    er_system_prompt,
    specialty_system_prompt,
)


class HospitalLLMPolicy(HospitalSpecialtyPolicy):
    def __init__(self, config, client=None):
        self.config = config
        self.client = client or OllamaClient()
        self.specialty_client = client or OllamaClient(
            base_url=settings.SPECIALTY_BASE_URL,
            api_key=settings.SPECIALTY_API_KEY,
        )
        self.departments = []
        self.agent_registry = None
        self.routing_mode = "llm"
        self.primary_router_mode = "rule_similarity"
        self.routing_seed = 0
        self.information_policy = None
        self.action_selector = "specialist_heuristic"
        self.diagnosis_catalog = None
        self.decision_deadline_minute = None
        self.flow_durations = {}
        self.memory_retriever = None

    def _decision(self, runtime, role, department=""):
        encounter = "index_encounter_id" in runtime.case_data
        observed = doctor_observation(runtime)
        if encounter and role == "specialty":
            event = encounter_evidence(runtime, "Consult", department)
            if event:
                observed["consults"].append({"department": department, "opinion": event["evidence"],
                                             "source_event_id": event["event_id"]})
        if encounter and self.memory_retriever is not None:
            runtime.memory_context = self.memory_retriever(runtime, observed)
            observed["longitudinal_memory"] = deepcopy(runtime.memory_context)
        execution_routing = None
        if encounter and self.agent_registry is not None:
            if self.routing_mode == "er_only":
                execution_routing = {"selected_specialty": None, "rationale": "Explicit ER-only baseline"}
            elif role == "specialty":
                execution_routing = {"selected_specialty": department,
                                     "rationale": "Execute the explicitly requested consultation binding"}
            else:
                # Logical specialist consultation at the existing decision point.
                # Physical resource handoffs still use the existing Consult action.
                candidates = [a["department"] for a in self.agent_registry.snapshot()["agents"]
                              if a["role"] == "specialty"]
                if self.primary_router_mode in {"rule_similarity", "adaptive"}:
                    execution_routing = self.agent_registry.select_specialty(
                        observed, runtime.memory_context, candidates,
                        router=self.primary_router_mode, seed=self.routing_seed)
                elif self.primary_router_mode in {"llm", "memory_aware_llm"}:
                    router = LLMRouter(self.client, self.agent_registry.get("er")["model"],
                                       use_memory=self.primary_router_mode == "memory_aware_llm")
                    try:
                        execution_routing = router.select(observed, candidates, audit=runtime.llm_audit,
                            cache=runtime.decision_cache.setdefault("primary_router_cache", {}))
                    except RoleCallError:
                        runtime.voi_state["primary_routing"] = deepcopy(runtime.llm_audit[-1]["routing_result"])
                        runtime.voi_state.setdefault("initial_primary_routing", deepcopy(runtime.voi_state["primary_routing"]))
                        raise
                else:
                    raise ValueError("Unknown primary router")
                runtime.voi_state["primary_routing"] = deepcopy(execution_routing)
                runtime.voi_state.setdefault("initial_primary_routing", deepcopy(execution_routing))
                runtime.voi_state.setdefault("primary_routing_history", []).append(deepcopy(execution_routing))
                selected = execution_routing.get("selected_specialty")
                if selected is not None:
                    role, department = "specialty", selected
                else:
                    # Preserve abstention and continue the ER decision loop.
                    role, department = "er", ""

        memory_ids = [
            r["memory_id"]
            for r in observed.get("longitudinal_memory", {}).get("records", [])
        ]

        evidence_records, excluded_evidence = diagnostic_evidence(runtime)
        evidence = [item["text"] for item in evidence_records]

        eligible_indices = [
            i
            for i, item in enumerate(evidence_records)
            if item["supports_finalization"]
        ]

        catalog = runtime.case_data.get(
            "available_tests",
            list(runtime.case_data.get("hidden_test_results", {})),
        )

        test_access = runtime.case_data.get("test_access", {})

        actor = "er" if role == "er" else department

        if test_access:
            catalog = [
                name
                for name in catalog
                if actor in test_access.get(
                    name,
                    ["er", *self.departments],
                )
            ]

        tests = [
            name
            for name in catalog
            if name not in runtime.completed_tests
            and not any(
                p["test_name"] == name
                for p in runtime.pending_results
            )
        ]

        treatments = [
            name
            for name in runtime.case_data
            .get("temporal_profile", {})
            .get("interventions", {})
            if name not in {t["id"] for t in runtime.interventions}
        ]

        departments = available_consult_departments(
            runtime,
            self.departments,
            department,
        )
        if encounter:
            allowed_consults = {e["target"] for e in runtime.case_data["current_encounter_events"]
                                if e["action"] == "Consult" and e["available_minute"] <= runtime.current_time_min}
            departments = [d for d in departments if d in allowed_consults]

        action_constraints = []
        # Review the current specialty's still-available workup before another
        # handoff. This does not select a test or inspect any unreleased result.
        if role == "specialty" and tests and departments:
            departments = []
            action_constraints.append({
                "action": "consult_specialty",
                "reason": "current_specialty_workup_available",
                "rationale": "Review available local tests before another specialty handoff.",
            })

        remaining_minutes = None
        if self.decision_deadline_minute is not None:
            remaining_minutes = self.decision_deadline_minute - runtime.current_time_min
            durations = self.flow_durations
            # Optimistic no-queue lower bound plus one minute reserved for a
            # final decision. Real resource contention can still cause censoring.
            consult_minutes = (durations["specialty_travel"]
                               + durations["specialty_consult"] + 2)
            if departments and remaining_minutes <= consult_minutes:
                departments = []
                action_constraints.append({
                    "action": "consult_specialty", "reason": "visit_time_budget",
                    "rationale": "Insufficient remaining time for another consultation and final review.",
                })

        routing = None
        agent = None

        if self.agent_registry is not None:
            routing = self.agent_registry.route(
                observed,
                departments,
                mode=self.routing_mode,
                seed=self.routing_seed,
            )

            departments = routing["allowed_departments"]

            agent = self.agent_registry.get(
                role,
                department if role == "specialty" else "",
            )
            if execution_routing is not None:
                routing = {**execution_routing, "allowed_departments": departments,
                           "scope": "executing_specialty; source-backed consultation menu"}

        actions = []

        decision_count = sum(
            a["role"] not in {"patient", "router"} and a["status"] == "success"
            for a in runtime.llm_audit
        )

        decision_count += runtime.voi_state.get("decision_count", 0)

        budget_exhausted = (
            decision_count >= self.config["max_decisions"] - 1
        )

        if not budget_exhausted:
            if len(runtime.question_history) < self.config["max_questions"]:
                actions.append("ask_patient")

            if tests and not runtime.pending_results:
                actions.append("request_test")

            if departments:
                actions.append("consult_specialty")

            if treatments:
                actions.append("treat")

        if remaining_minutes is not None:
            durations = self.flow_durations
            review_minutes = durations["result_hold"] + durations["er_travel"] + 2
            def wait_minutes(name):
                delay = test_timing(runtime.case_data, name, durations)["turnaround_min"]
                if encounter:
                    event = next(e for e in runtime.case_data["current_encounter_events"]
                                 if e["action"] == "Test" and e["target"] == name)
                    delay = max(delay, event["available_minute"] - runtime.current_time_min)
                return delay
            timely_tests = [name for name in tests if remaining_minutes > wait_minutes(name) + review_minutes]
            if timely_tests != tests:
                action_constraints.append({
                    "action": "request_test", "reason": "visit_time_budget",
                    "excluded_targets": [name for name in tests if name not in timely_tests],
                    "rationale": "Reserve time for result release and final review.",
                })
                tests = timely_tests
                if not tests and "request_test" in actions:
                    actions.remove("request_test")
            if remaining_minutes <= durations["er_travel"] + durations["er_assessment"] + 2:
                for action in ("ask_patient", "treat"):
                    if action in actions:
                        actions.remove(action)
                        action_constraints.append({
                            "action": action, "reason": "visit_time_budget",
                            "rationale": "Reserve remaining visit time for a final decision.",
                        })

        if runtime.pending_results and (
            not runtime.reassessment_pending or not actions
        ):
            return {
                "action": "await_results",
                "rationale": (
                    "Reassessment requested, but no decision budget or available "
                    "action remains; await pending results."
                    if runtime.reassessment_pending
                    else "Await the already ordered objective results."
                ),
                "target_department": (
                    department or runtime.target_department
                ),
                "assessment_summary": runtime.assessment_summary,
            }

        allow_unresolved = budget_exhausted or not actions
        if encounter:
            questions = [e["target"] for e in runtime.case_data["current_encounter_events"]
                         if e["action"] == "Ask" and e["available_minute"] <= runtime.current_time_min
                         and not any(q["question"] == e["target"] for q in runtime.question_history)]
            if not questions and "ask_patient" in actions:
                actions.remove("ask_patient")
            if "treat" in actions:
                actions.remove("treat")
            allow_unresolved = budget_exhausted or not actions

        if (
            eligible_indices or allow_unresolved
        ) and not runtime.pending_results:
            actions.insert(0, "diagnose")
        if self.information_policy is not None and not runtime.pending_results:
            # Diagnose is always evaluated by Q, including at the prior.
            # Without objective support the runtime records an unresolved stop.
            if "diagnose" not in actions:
                actions.insert(0, "diagnose")
            allow_unresolved = True

        termination_reason = (
            "decision_budget_exhausted"
            if budget_exhausted
            else "visit_time_budget_exhausted"
            if allow_unresolved and any(
                c["reason"] == "visit_time_budget" for c in action_constraints)
            else "available_steps_exhausted"
        )

        payload = {
            "role": role,
            "department": department,
            "observation": observed,
            "evidence": evidence,
            "available_tests": tests,
            "available_departments": departments,
            "evidence_records": evidence_records,
            "excluded_evidence": excluded_evidence,
            "supported_diagnosis_eligible_indices": eligible_indices,
            "allow_unresolved_finalization": allow_unresolved,
            "decision_budget_remaining": max(
                0,
                self.config["max_decisions"] - decision_count,
            ),
            "allowed_actions": actions,
            "remaining_visit_minutes": remaining_minutes,
            "action_constraints": action_constraints,
            "available_interventions": treatments,
            "instruction": (
                "Return only JSON: action, target, rationale, assessment, "
                "department, certainty (supported or unresolved), "
                "evidence_indices (zero-based indices into evidence). "
                "A supported diagnosis must cite at least one eligible objective "
                "finding that actually supports it; unknown answers, vital values "
                "alone and specialty opinions alone do not qualify. "
                "Unresolved finalization is allowed ONLY when "
                "allow_unresolved_finalization is true. Otherwise choose a useful "
                "allowed question, test or consult instead of ending an uncertain "
                "case. Prefer a targeted question, then objective workup, then "
                "specialty review; do not order a test merely because it is "
                "available. For ask_patient, target MUST be the complete question "
                "ending in '?' (example: 'When did your symptoms start?'). "
                "For request_test/consult_specialty/treat, target is an available "
                "item name. For diagnose, target is a diagnosis or unresolved "
                "presenting problem, NEVER a department. Diagnose immediately when "
                "objective evidence is decisive. Never invent confirmation to "
                "satisfy the gate."
            ),
        }

        payload["instruction"] += (
            " Keep rationale within 240 characters, assessment within 160, "
            "and target within 240. Do not repeat text or array items. "
            "Return one compact JSON object."
        )

        memory_records = observed.get(
            "longitudinal_memory",
            {}
        ).get("records", [])

        usable_memory = [
            record
            for record in memory_records
            if record.get("status_as_of_visit") != "superseded"
        ]

        if usable_memory:
            payload["instruction"] += (
                " Relevant non-superseded longitudinal memory is contextual "
                "diagnostic evidence. When current objective findings are "
                "compatible with multiple diagnoses, use relevant longitudinal "
                "memory to distinguish among those diagnoses. Historical memory "
                "does NOT count as current objective confirmation by itself, "
                "but it may determine which diagnosis best explains the current "
                "objective evidence. Cite the memory IDs actually used."
            )

        if (
            routing is not None
            and self.routing_mode == "adaptive"
            and len(departments) == 1
        ):
            payload["instruction"] += (
                " Adaptive routing identified a preferred specialty. "
                "If current ER-accessible evidence cannot distinguish the "
                "candidate diagnoses and no decisive objective finding is "
                "available, consult the routed specialty before finalizing. "
                "Do not finalize solely from a nondiscriminative screening result."
        )


        if self.diagnosis_catalog:
            payload["diagnosis_catalog"] = self.diagnosis_catalog

            payload["instruction"] += (
                " For a supported diagnosis use exactly one diagnosis_catalog "
                "label as target. The catalog is the same for all patients; "
                "select using released evidence only."
            )

        candidates = candidate_actions(runtime, actions, tests, departments,
                                       self.information_policy.model.artifact if self.information_policy else None)
        runtime.voi_state.setdefault("diagnosis_belief", DiagnosisBelief().snapshot())
        payload["candidate_actions"] = candidates
        if encounter:
            payload["instruction"] += (
                " Select one available candidate action. Ask targets must exactly match the listed questions. "
                "Return only the decision JSON, not new test results or patient facts."
            )

        def validate(raw):
            text = raw.strip()

            if text.startswith("```") and text.endswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]

            row = json.loads(text)

            if not isinstance(row, dict):
                raise ValueError("Decision must be an object")

            action = row.get("action")

            # ---------------------------------------------------------
            # Memory citation validation
            #
            # Invalid citation IDs should NOT fail the whole episode.
            # Keep valid IDs and record invalid IDs separately.
            # ---------------------------------------------------------
            references = row.get("memory_ids", [])

            if not isinstance(references, list):
                references = []

            valid_references = []
            invalid_references = []

            for ref in references:
                if isinstance(ref, str) and ref in memory_ids:
                    if ref not in valid_references:
                        valid_references.append(ref)
                else:
                    invalid_references.append(ref)

            row["memory_ids"] = valid_references
            row["_invalid_memory_ids"] = invalid_references

            # Question normalization flag always exists.
            row["_question_normalized"] = False

            if action not in actions:
                raise ValueError("Unavailable or repeated action")

            for key in ("target", "rationale", "assessment"):
                if (
                    not isinstance(row.get(key), str)
                    or not row[key].strip()
                ):
                    raise ValueError(f"Missing {key}")

                row[key] = row[key].strip()

                limits = {
                    "target": 240,
                    "rationale": 240,
                    "assessment": 160,
                }

                if len(row[key]) > limits[key]:
                    raise ValueError(
                        f"Decision {key} exceeds compact output limit"
                    )

            if (
                action == "request_test"
                and row["target"] not in tests
            ):
                raise ValueError("Unavailable test")

            if (
                action == "treat"
                and row["target"] not in treatments
            ):
                raise ValueError("Unavailable intervention")

            if action == "consult_specialty":
                row["target"] = normalize_department(
                    row["target"],
                    default="",
                )

                if row["target"] not in departments:
                    raise ValueError("Unavailable department")

            # ---------------------------------------------------------
            # Normalize missing terminal question mark.
            #
            # This is only a formatting repair and does not change
            # the semantic content of the action.
            # ---------------------------------------------------------
            if action == "ask_patient":
                target = row["target"].strip()

                if not target.endswith(("?", "？")):
                    target = target.rstrip(".! ") + "?"
                    row["_question_normalized"] = True

                row["target"] = target
                if encounter and target not in questions:
                    raise ValueError("Question is absent from available source events")

                if any(
                    q["question"].casefold()
                    == row["target"].casefold()
                    for q in runtime.question_history
                ):
                    raise ValueError("Repeated question")

            if action == "diagnose":
                if (
                    self.diagnosis_catalog
                    and row.get("certainty") == "supported"
                    and row["target"] not in self.diagnosis_catalog
                ):
                    raise ValueError(
                        "Diagnosis target must use the shared diagnosis catalog"
                    )

                if row.get("certainty") not in {
                    "supported",
                    "unresolved",
                }:
                    raise ValueError(
                        "Diagnosis certainty required"
                    )

                indices = row.get("evidence_indices", [])

                if (
                    not isinstance(indices, list)
                    or any(
                        type(i) is not int
                        or not 0 <= i < len(evidence)
                        for i in indices
                    )
                ):
                    raise ValueError(
                        "Invalid evidence references"
                    )

                if (
                    row["certainty"] == "supported"
                    and not set(indices).intersection(
                        eligible_indices
                    )
                ):
                    raise ValueError(
                        "Supported diagnosis needs a cited eligible objective finding"
                    )

                if (
                    row["certainty"] == "unresolved"
                    and not allow_unresolved
                ):
                    raise ValueError(
                        "Uncertainty must advance to an available step "
                        "before finalization"
                    )

                label = canonicalize_department_text(
                    row["target"]
                )

                if (
                    label in SUPPORTED_DEPARTMENTS
                    or label in DEPARTMENT_ALIASES
                ):
                    if row["certainty"] == "supported":
                        raise ContractValidationError("A department is not a supported diagnosis",
                            code="diagnosis_is_department", field="target", value=row["target"])

                if row["certainty"] == "unresolved":
                    row["target"] = (
                        "Unresolved presenting complaint: "
                        + observed["chief_complaint"]
                    )

            row["department"] = normalize_department(
                row.get("department", department),
                default="general_medicine",
            )

            return row

        if routing is not None:
            payload["routing_context"] = {
                **routing,
                "executing_agent": agent,
            }

        if memory_ids:
            payload["memory_instruction"] = (
                "Return memory_ids listing only provided memory IDs used in "
                "your decision (empty if none). Historical opinions and "
                "superseded facts are not current confirmations."
            )

        if self.information_policy is not None:
            payload["voi_model_sha256"] = (
                self.information_policy.model.fingerprint
            )

        key = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()

        if key in runtime.decision_cache:
            return deepcopy(runtime.decision_cache[key])

        properties = {
            "action": {
                "type": "string",
                "enum": actions,
            },
            "target": {
                "type": "string",
                "maxLength": 240,
            },
            "rationale": {
                "type": "string",
                "maxLength": 240,
            },
            "assessment": {
                "type": "string",
                "maxLength": 160,
            },
            "department": {
                "type": "string",
                "enum": SUPPORTED_DEPARTMENTS,
            },
            "certainty": {
                "type": "string",
                "enum": [
                    "supported",
                    "unresolved",
                ],
            },
            "evidence_indices": {
                "type": "array",
                "maxItems": min(4, len(evidence)),
                "uniqueItems": True,
                "items": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": max(
                        0,
                        len(evidence) - 1,
                    ),
                },
            },
        }

        schema = {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        }

        if memory_ids:
            properties["memory_ids"] = {
                "type": "array",
                "uniqueItems": True,
                "maxItems": min(
                    4,
                    len(memory_ids),
                ),
                "items": {
                    "type": "string",
                    "enum": memory_ids,
                },
            }

            schema["required"].append(
                "memory_ids"
            )

        alternatives = []

        next_actions = [
            a
            for a in actions
            if a != "diagnose"
        ]

        for next_action in next_actions:
            branch = deepcopy(schema)

            branch["properties"]["action"]["enum"] = [
                next_action
            ]

            targets = {
                "request_test": tests,
                "consult_specialty": departments,
                "treat": treatments,
            }

            if next_action in targets:
                branch["properties"]["target"]["enum"] = list(
                    targets[next_action]
                )

            # Do NOT require '?' at schema-generation stage.
            # The validator normalizes a missing question mark.
            elif next_action == "ask_patient":
                branch["properties"]["target"].pop(
                    "pattern",
                    None,
                )
                if encounter:
                    branch["properties"]["target"]["enum"] = questions

            alternatives.append(branch)

        if "diagnose" in actions:
            branch = deepcopy(schema)
            branch["properties"]["target"]["description"] = (
                "Clinical diagnosis or unresolved presenting problem, NEVER a department name. "
                "department is the specialty field, target is the clinical problem. Do not invent evidence.")
            branch["properties"]["target"]["not"] = {
                "enum": sorted(set(SUPPORTED_DEPARTMENTS) | set(DEPARTMENT_ALIASES))}

            branch["properties"]["action"]["enum"] = [
                "diagnose"
            ]

            if self.diagnosis_catalog:
                branch["properties"]["target"]["enum"] = (
                    list(self.diagnosis_catalog)
                    + (
                        ["Unresolved"]
                        if allow_unresolved
                        else []
                    )
                )

            branch["properties"]["certainty"]["enum"] = (
                (
                    ["supported"]
                    if eligible_indices
                    else []
                )
                + (
                    ["unresolved"]
                    if allow_unresolved
                    else []
                )
            )

            alternatives.append(branch)

        schema = (
            alternatives[0]
            if len(alternatives) == 1
            else {
                "anyOf": alternatives,
            }
        )

        proposed = None

        if (
            self.information_policy is not None
            and role == "er"
            and not encounter
        ):
            proposed = self.information_policy.propose(
                runtime,
                observed,
                actions=actions,
                tests=tests,
                departments=departments,
                evidence_records=evidence_records,
                allow_unresolved=allow_unresolved,
            )

            if (
                proposed
                and proposed["action"]
                == "retrieve_memory"
            ):
                runtime.voi_state[
                    "memory_retrieved"
                ] = True

                runtime.memory_context = deepcopy(
                    runtime.voi_memory_pool
                )

                return self._decision(
                    runtime,
                    role,
                    department,
                )

        if proposed is not None:
            row = validate(
                json.dumps(proposed)
            )

            runtime.voi_state[
                "decision_count"
            ] = (
                runtime.voi_state.get(
                    "decision_count",
                    0,
                )
                + 1
            )

            decision_audit = (
                runtime.voi_state["history"][-1]
            )

        else:
            try:
                row = role_call(
                    (
                        self.specialty_client
                        if role == "specialty"
                        else self.client
                    ),
                    role=role,
                    model=(
                        agent["model"]
                        if agent
                        else (
                            settings.SPECIALTY_OLLAMA_MODEL
                            if role == "specialty"
                            else settings.OLLAMA_MODEL
                        )
                    ),
                    system=(
                        specialty_system_prompt(department)
                        if role == "specialty"
                        else er_system_prompt()
                    ),

                    payload=payload,
                    audit=runtime.llm_audit,
                    validate=validate,
                    schema=schema,
                    repair_codes=("diagnosis_is_department",),
                )

            finally:
                if routing is not None:
                    runtime.llm_audit[-1]["routing"] = {
                        **routing,
                        "executing_agent": agent,
                    }

            decision_audit = runtime.llm_audit[-1]

            # The specialist is always called first on the encounter path.
            # An explicit outcome model may then select a source-backed action.
            if encounter and self.information_policy is not None:
                proposal = self.information_policy.propose(
                    runtime, observed, actions=actions, tests=tests, departments=departments,
                    evidence_records=evidence_records, allow_unresolved=allow_unresolved)
                if proposal and any(c["action"] == proposal["action"] and
                                    (c["target"] is None or c["target"] == proposal["target"]) for c in candidates):
                    decision_audit["specialist_proposal"] = {k: row[k] for k in ("action", "target", "rationale")}
                    row = validate(json.dumps(proposal))
                    decision_audit["action_selector"] = (
                        "explicit_outcome_voi" if self.action_selector == "bayesian_voi" else "explicit_outcome_ig")
                else:
                    decision_audit["action_selector"] = "specialist_heuristic_no_supported_voi"

        decision_audit["candidate_actions"] = candidates
        decision_audit.setdefault("action_selector", "specialist_heuristic" if encounter else "legacy_policy")
        if self.information_policy is not None:
            selection_status = deepcopy(runtime.voi_state.get("selector_status", {}))
            selection_status["executed_selector"] = (
                self.action_selector if selection_status.get("status") == "available" else "specialist_heuristic")
        elif self.action_selector in {"bayesian_voi", "information_gain"}:
            selection_status = {"selector": self.action_selector, "status": "unavailable",
                                "reason": "missing_outcome_model", "executed_selector": "specialist_heuristic"}
        elif self.action_selector == "random":
            executable = [c for c in candidates if c["target"] is not None or
                          (c["action"] == row["action"])]
            selection_status = select_action(executable, selector="random",
                                             seed=self.routing_seed + decision_count)
            chosen = selection_status["selected_action"]
            if chosen and chosen["target"] is not None:
                row = validate(json.dumps({**row, "action": chosen["action"], "target": chosen["target"],
                                           "rationale": "Seeded Random selector chose this available source action."}))
            selection_status["executed_selector"] = "random"
        else:
            selection_status = {"selector": "specialist_heuristic", "status": "available",
                                "executed_selector": "specialist_heuristic"}
        decision_audit["selector_status"] = selection_status
        runtime.voi_state["selector_status"] = deepcopy(selection_status)
        if encounter:
            decision_audit["memory_context"] = deepcopy(runtime.memory_context)
            decision_audit["retrieval_query"] = memory_query(observed)

        if routing is not None:
            decision_audit["routing"] = {
                **routing,
                "executing_agent": agent,
            }

        invalid_memory_ids = row.pop(
            "_invalid_memory_ids",
            [],
        )

        question_normalized = row.pop(
            "_question_normalized",
            False,
        )

        decision_audit["decision"] = {
            key: row[key]
            for key in (
                "action",
                "target",
                "rationale",
            )
        }

        decision_audit["decision_validation"] = {
            "excluded_evidence": excluded_evidence,
            "cited_evidence": (
                [
                    evidence_records[i]
                    for i in row.get(
                        "evidence_indices",
                        [],
                    )
                ]
                if row["action"] == "diagnose"
                else []
            ),
            "termination_reason": (
                termination_reason
                if (
                    row["action"] == "diagnose"
                    and row["certainty"]
                    == "unresolved"
                )
                else None
            ),
            "clinical_support_verified": False,
            "remaining_visit_minutes": remaining_minutes,
            "action_constraints": action_constraints,
        }

        decision_audit["memory_citations"] = {
            "ids": row.get(
                "memory_ids",
                [],
            ),
            "reported": (
                "memory_ids" in row
                or not memory_ids
            ),
            "invalid_ids": invalid_memory_ids,
            "valid": (
                len(invalid_memory_ids) == 0
            ),
        }

        decision_audit["output_normalization"] = {
            "question_punctuation_fixed": (
                question_normalized
            )
        }

        result = {
            "action": {
                "ask_patient": "ask_history",
                "request_test": "order_test",
                "consult_specialty": "request_specialty",
                "treat": "treat",
                "diagnose": "er_finalize",
            }[row["action"]],
            "target": row["target"],
            "rationale": row["rationale"],
            "assessment_summary": row[
                "assessment"
            ],
            "target_department": row[
                "department"
            ],
            "certainty": row.get(
                "certainty",
                "unresolved",
            ),
            "alternatives": [],
        }

        if row["action"] == "ask_patient":
            if "synthea_v2_patient_input" in runtime.case_data:
                patient = PatientAgent({"synthea_v2_patient_input": runtime.case_data["synthea_v2_patient_input"]})
                answer = patient.answer(row["target"], runtime)
                result.update(question=row["target"], answer=answer,
                              answer_status="unknown" if patient.last_grounding.get("unknown") else "provided")
                decision_audit["patient_grounding"] = patient.last_grounding
                runtime.decision_cache[key] = deepcopy(result)
                return result
            if encounter:
                event = encounter_evidence(runtime, "Ask", row["target"])
                result.update(question=row["target"], answer=event["evidence"] if event else "Unknown",
                              answer_status="provided" if event else "unknown")
                decision_audit["released_event"] = event
                runtime.decision_cache[key] = deepcopy(result)
                return result
            patient = PatientAgent(
                runtime.case_data
            )

            patient.client = self.client

            result.update(
                question=row["target"],
                answer=patient.answer(
                    row["target"],
                    runtime,
                    required=True,
                ),
            )

            selection = (
                runtime.llm_audit[-1]
                .get(
                    "grounding",
                    {},
                )
                .get(
                    "selection",
                    {},
                )
            )

            result["answer_status"] = (
                "unknown"
                if selection.get(
                    "unknown"
                )
                else "provided"
            )

        elif row["action"] == "request_test":
            result["recommended_tests"] = [
                row["target"]
            ]

        elif row["action"] == "consult_specialty":
            result["target_department"] = (
                row["target"]
            )

        elif row["action"] == "diagnose":
            result["assessment_summary"] = (
                row["target"]
            )

        runtime.decision_cache[key] = deepcopy(
            result
        )

        return result

    def evaluate_er_case(
        self,
        runtime,
        *,
        doctor_id,
    ):
        return self._decision(
            runtime,
            "er",
        )

    def complete_consult(
        self,
        runtime,
        *,
        department,
        specialist_id,
    ):
        result = self._decision(
            runtime,
            "specialty",
            department,
        )

        result.update(
            department=department,
            consult_note=result["rationale"],
        )
        if "index_encounter_id" in runtime.case_data:
            event = encounter_evidence(runtime, "Consult", department)
            result["consult_note"] = event["evidence"] if event else "No consultation evidence in source data"

        if result["action"] == "er_finalize":
            result["final_diagnosis"] = (
                result["assessment_summary"]
            )

        return result

    @staticmethod
    def build_objective_finding(
        runtime,
        test_name,
    ):
        if "index_encounter_id" in runtime.case_data:
            event = encounter_evidence(runtime, "Test", test_name)
            return f"{test_name}: {event['evidence']}" if event else ""
        entry = (
            runtime.case_data
            .get(
                "hidden_test_results",
                {},
            )
            .get(
                test_name,
                {},
            )
        )

        result = (
            entry.get("result")
            if isinstance(entry, dict)
            else None
        )

        return (
            f"{test_name}: {result}"
            if result
            else ""
        )

    @staticmethod
    def build_test_result_summary(
        runtime,
        test_name,
    ):
        finding = (
            HospitalLLMPolicy
            .build_objective_finding(
                runtime,
                test_name,
            )
        )

        return {
            "test_name": test_name,
            "summary": (
                finding
                or "Result unavailable in source data"
            ),
            "impression": (
                finding
                or "Result unavailable in source data"
            ),
            "metrics": [],
            "source": (
                "case_data"
                if finding
                else "missing"
            ),
            "synthetic": False,
        }
