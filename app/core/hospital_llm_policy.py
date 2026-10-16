"""Evidence-only LLM role policy for the parallel scheduler.

The simulator owns results/time/resources; models choose one validated action.
Demo gold labels and unreleased results never enter model observations.
"""
import hashlib
import json
from copy import deepcopy

from app.agents.patient_agent import PatientAgent
from app.config import settings
from app.core.clinical_observation import doctor_observation
from app.core.diagnostic_evidence import diagnostic_evidence
from app.core.clinical_followup import available_consult_departments
from app.core.hospital_specialty_policy import HospitalSpecialtyPolicy
from app.llm.ollama_client import OllamaClient
from app.llm.role_call import role_call
from app.utils.department_catalog import normalize_department, SUPPORTED_DEPARTMENTS, DEPARTMENT_ALIASES, canonicalize_department_text


class HospitalLLMPolicy(HospitalSpecialtyPolicy):
    def __init__(self, config, client=None):
        self.config = config
        self.client = client or OllamaClient()
        self.specialty_client = client or OllamaClient(base_url=settings.SPECIALTY_BASE_URL,
                                                       api_key=settings.SPECIALTY_API_KEY)
        self.departments = []
        self.agent_registry = None
        self.routing_mode = "llm"
        self.routing_seed = 0
        self.information_policy = None
        self.diagnosis_catalog = None

    def _decision(self, runtime, role, department=""):
        observed = doctor_observation(runtime)
        memory_ids = [r["memory_id"] for r in observed.get("longitudinal_memory", {}).get("records", [])]
        evidence_records, excluded_evidence = diagnostic_evidence(runtime)
        evidence = [item["text"] for item in evidence_records]
        eligible_indices = [i for i, item in enumerate(evidence_records) if item["supports_finalization"]]
        catalog = runtime.case_data.get("available_tests", list(runtime.case_data.get("hidden_test_results", {})))
        tests = [name for name in catalog if name not in runtime.completed_tests
                 and not any(p["test_name"] == name for p in runtime.pending_results)]
        treatments = [name for name in runtime.case_data.get("temporal_profile", {}).get("interventions", {})
                      if name not in {t["id"] for t in runtime.interventions}]
        departments = available_consult_departments(runtime, self.departments, department)
        routing = None
        agent = None
        if self.agent_registry is not None:
            routing = self.agent_registry.route(observed, departments, mode=self.routing_mode, seed=self.routing_seed)
            departments = routing["allowed_departments"]
            agent = self.agent_registry.get(role, department if role == "specialty" else "")
        actions = []
        decision_count = sum(a["role"] != "patient" and a["status"] == "success" for a in runtime.llm_audit)
        decision_count += runtime.voi_state.get("decision_count", 0)
        budget_exhausted = decision_count >= self.config["max_decisions"] - 1
        if not budget_exhausted:
            if len(runtime.question_history) < self.config["max_questions"]:
                actions.append("ask_patient")
            if tests and not runtime.pending_results:
                actions.append("request_test")
            if departments:
                actions.append("consult_specialty")
            if treatments:
                actions.append("treat")
        if runtime.pending_results and (not runtime.reassessment_pending or not actions):
            # Pending work needs no model request or fabricated interim decision.
            return {"action": "await_results", "rationale": (
                        "Reassessment requested, but no decision budget or available action remains; await pending results."
                        if runtime.reassessment_pending else "Await the already ordered objective results."),
                    "target_department": department or runtime.target_department,
                    "assessment_summary": runtime.assessment_summary}
        allow_unresolved = budget_exhausted or not actions
        if (eligible_indices or allow_unresolved) and not runtime.pending_results:
            actions.insert(0, "diagnose")
        termination_reason = "decision_budget_exhausted" if budget_exhausted else "available_steps_exhausted"
        payload = {"role": role, "department": department, "observation": observed,
                   "evidence": evidence, "available_tests": tests, "available_departments": departments,
                   "evidence_records": evidence_records, "excluded_evidence": excluded_evidence,
                   "supported_diagnosis_eligible_indices": eligible_indices,
                   "allow_unresolved_finalization": allow_unresolved,
                   "decision_budget_remaining": max(0, self.config["max_decisions"] - decision_count),
                   "allowed_actions": actions, "available_interventions": treatments,
                   "instruction": "Return only JSON: action, target, rationale, assessment, department, certainty (supported or unresolved), evidence_indices (zero-based indices into evidence). A supported diagnosis must cite at least one eligible objective finding that actually supports it; unknown answers, vital values alone and specialty opinions alone do not qualify. Unresolved finalization is allowed ONLY when allow_unresolved_finalization is true. Otherwise choose a useful allowed question, test or consult instead of ending an uncertain case. Prefer a targeted question, then objective workup, then specialty review; do not order a test merely because it is available. For ask_patient, target MUST be the complete question ending in '?' (example: 'When did your symptoms start?'). For request_test/consult_specialty/treat, target is an available item name. For diagnose, target is a diagnosis or unresolved presenting problem, NEVER a department. Diagnose immediately when objective evidence is decisive. Never invent confirmation to satisfy the gate."}

        payload["instruction"] += " Keep rationale within 240 characters, assessment within 160, and target within 240. Do not repeat text or array items. Return one compact JSON object."
        if self.diagnosis_catalog:
            payload["diagnosis_catalog"] = self.diagnosis_catalog
            payload["instruction"] += " For a supported diagnosis use exactly one diagnosis_catalog label as target. The catalog is the same for all patients; select using released evidence only."

        def validate(raw):
            text = raw.strip()
            if text.startswith("```") and text.endswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            row = json.loads(text)
            if not isinstance(row, dict):
                raise ValueError("Decision must be an object")
            action = row.get("action")
            references = row.get("memory_ids", [])
            if (not isinstance(references, list) or any(not isinstance(i, str) or i not in memory_ids for i in references)
                    or len(set(references)) != len(references)):
                raise ValueError("Invalid memory citations")
            if action not in actions:
                raise ValueError("Unavailable or repeated action")
            for key in ("target", "rationale", "assessment"):
                if not isinstance(row.get(key), str) or not row[key].strip():
                    raise ValueError(f"Missing {key}")
                row[key] = row[key].strip()
                if len(row[key]) > {"target": 240, "rationale": 240, "assessment": 160}[key]:
                    raise ValueError(f"Decision {key} exceeds compact output limit")
            if action == "request_test" and row["target"] not in tests:
                raise ValueError("Unavailable test")
            if action == "treat" and row["target"] not in treatments:
                raise ValueError("Unavailable intervention")
            if action == "consult_specialty":
                row["target"] = normalize_department(row["target"], default="")
                if row["target"] not in departments:
                    raise ValueError("Unavailable department")
            if action == "ask_patient" and any(q["question"].casefold() == row["target"].casefold() for q in runtime.question_history):
                raise ValueError("Repeated question")
            if action == "ask_patient" and not row["target"].endswith(("?", "？")):
                raise ValueError("Patient target must be a complete question ending in ?")
            if action == "diagnose":
                if self.diagnosis_catalog and row.get("certainty") == "supported" and row["target"] not in self.diagnosis_catalog:
                    raise ValueError("Diagnosis target must use the shared diagnosis catalog")
                if row.get("certainty") not in {"supported", "unresolved"}:
                    raise ValueError("Diagnosis certainty required")
                indices = row.get("evidence_indices", [])
                if not isinstance(indices, list) or any(type(i) is not int or not 0 <= i < len(evidence) for i in indices):
                    raise ValueError("Invalid evidence references")
                if row["certainty"] == "supported" and not set(indices).intersection(eligible_indices):
                    raise ValueError("Supported diagnosis needs a cited eligible objective finding")
                if row["certainty"] == "unresolved" and not allow_unresolved:
                    raise ValueError("Uncertainty must advance to an available step before finalization")
                label = canonicalize_department_text(row["target"])
                if label in SUPPORTED_DEPARTMENTS or label in DEPARTMENT_ALIASES:
                    if row["certainty"] == "supported":
                        raise ValueError("A department is not a supported diagnosis")
                if row["certainty"] == "unresolved":
                    row["target"] = "Unresolved presenting complaint: " + observed["chief_complaint"]
            row["department"] = normalize_department(row.get("department", department), default="general_medicine")
            return row

        if routing is not None:
            payload["routing_context"] = {**routing, "executing_agent": agent}
        if memory_ids:
            payload["memory_instruction"] = "Return memory_ids listing only provided memory IDs used in your decision (empty if none). Historical opinions and superseded facts are not current confirmations."
        if self.information_policy is not None:
            payload["voi_model_sha256"] = self.information_policy.model.fingerprint
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        if key in runtime.decision_cache:
            return deepcopy(runtime.decision_cache[key])
        properties = {"action": {"type": "string", "enum": actions},
                      "target": {"type": "string", "maxLength": 240}, "rationale": {"type": "string", "maxLength": 240},
                      "assessment": {"type": "string", "maxLength": 160},
                      "department": {"type": "string", "enum": SUPPORTED_DEPARTMENTS},
                      "certainty": {"type": "string", "enum": ["supported", "unresolved"]},
                      "evidence_indices": {"type": "array", "maxItems": min(4, len(evidence)), "uniqueItems": True,
                                           "items": {"type": "integer", "minimum": 0, "maximum": max(0, len(evidence) - 1)}}}
        schema = {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}
        if memory_ids:
            properties["memory_ids"] = {"type": "array", "uniqueItems": True, "maxItems": min(4, len(memory_ids)),
                                        "items": {"type": "string", "enum": memory_ids}}
            schema["required"].append("memory_ids")
        # Constrain the action/certainty combination at generation time too.
        # This avoids an extra model call solely to correct a premature ending.
        alternatives = []
        next_actions = [a for a in actions if a != "diagnose"]
        for next_action in next_actions:
            branch = deepcopy(schema)
            branch["properties"]["action"]["enum"] = [next_action]
            targets = {"request_test": tests, "consult_specialty": departments, "treat": treatments}
            if next_action in targets:
                branch["properties"]["target"]["enum"] = list(targets[next_action])
            elif next_action == "ask_patient":
                branch["properties"]["target"]["pattern"] = r"[?？]$"
            alternatives.append(branch)
        if "diagnose" in actions:
            branch = deepcopy(schema)
            branch["properties"]["action"]["enum"] = ["diagnose"]
            if self.diagnosis_catalog:
                branch["properties"]["target"]["enum"] = list(self.diagnosis_catalog) + (["Unresolved"] if allow_unresolved else [])
            branch["properties"]["certainty"]["enum"] = (["supported"] if eligible_indices else []) + (["unresolved"] if allow_unresolved else [])
            alternatives.append(branch)
        schema = alternatives[0] if len(alternatives) == 1 else {"anyOf": alternatives}
        proposed = None
        if self.information_policy is not None and role == "er":
            proposed = self.information_policy.propose(runtime, observed, actions=actions, tests=tests,
                departments=departments, evidence_records=evidence_records, allow_unresolved=allow_unresolved)
            if proposed and proposed["action"] == "retrieve_memory":
                runtime.voi_state["memory_retrieved"] = True
                runtime.memory_context = deepcopy(runtime.voi_memory_pool)
                return self._decision(runtime, role, department)
        if proposed is not None:
            row = validate(json.dumps(proposed))
            runtime.voi_state["decision_count"] = runtime.voi_state.get("decision_count", 0) + 1
            decision_audit = runtime.voi_state["history"][-1]
        else:
            try:
                row = role_call(self.specialty_client if role == "specialty" else self.client,
                            role=role, model=agent["model"] if agent else (settings.SPECIALTY_OLLAMA_MODEL if role == "specialty" else settings.OLLAMA_MODEL),
                            system="You are a physician in a fictional hospital simulation. Use only the provided observations. Never assume unreleased results. Every decision needs a brief evidence-based rationale.",
                            payload=payload, audit=runtime.llm_audit, validate=validate, schema=schema)
            finally:
                if routing is not None:
                    runtime.llm_audit[-1]["routing"] = {**routing, "executing_agent": agent}
            decision_audit = runtime.llm_audit[-1]
        if routing is not None:
            decision_audit["routing"] = {**routing, "executing_agent": agent}
        decision_audit["decision"] = {key: row[key] for key in ("action", "target", "rationale")}
        decision_audit["decision_validation"] = {
            "excluded_evidence": excluded_evidence,
            "cited_evidence": [evidence_records[i] for i in row.get("evidence_indices", [])]
                if row["action"] == "diagnose" else [],
            "termination_reason": termination_reason if row["action"] == "diagnose" and row["certainty"] == "unresolved" else None,
            "clinical_support_verified": False,
        }
        decision_audit["memory_citations"] = {"ids": row.get("memory_ids", []),
                                                   "reported": "memory_ids" in row or not memory_ids}
        result = {"action": {"ask_patient": "ask_history", "request_test": "order_test",
                              "consult_specialty": "request_specialty", "treat": "treat", "diagnose": "er_finalize"}[row["action"]],
                  "target": row["target"], "rationale": row["rationale"],
                  "assessment_summary": row["assessment"], "target_department": row["department"],
                  "certainty": row.get("certainty", "unresolved"), "alternatives": []}
        if row["action"] == "ask_patient":
            patient = PatientAgent(runtime.case_data)
            patient.client = self.client
            result.update(question=row["target"], answer=patient.answer(row["target"], runtime, required=True))
            selection = runtime.llm_audit[-1].get("grounding", {}).get("selection", {})
            result["answer_status"] = "unknown" if selection.get("unknown") else "provided"
        elif row["action"] == "request_test":
            result["recommended_tests"] = [row["target"]]
        elif row["action"] == "consult_specialty":
            result["target_department"] = row["target"]
        elif row["action"] == "diagnose":
            result["assessment_summary"] = row["target"]
        runtime.decision_cache[key] = deepcopy(result)
        return result

    def evaluate_er_case(self, runtime, *, doctor_id):
        return self._decision(runtime, "er")

    def complete_consult(self, runtime, *, department, specialist_id):
        result = self._decision(runtime, "specialty", department)
        result.update(department=department, consult_note=result["rationale"])
        if result["action"] == "er_finalize":
            result["final_diagnosis"] = result["assessment_summary"]
        return result

    @staticmethod
    def build_objective_finding(runtime, test_name):
        entry = runtime.case_data.get("hidden_test_results", {}).get(test_name, {})
        result = entry.get("result") if isinstance(entry, dict) else None
        return f"{test_name}: {result}" if result else ""

    @staticmethod
    def build_test_result_summary(runtime, test_name):
        finding = HospitalLLMPolicy.build_objective_finding(runtime, test_name)
        return {"test_name": test_name, "summary": finding or "Result unavailable in source data",
                "impression": finding or "Result unavailable in source data", "metrics": [],
                "source": "case_data" if finding else "missing", "synthetic": False}
