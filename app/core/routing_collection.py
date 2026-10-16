"""Offline same-observation probes. Gold labels stay outside each model prompt."""
import json
from app.llm.role_call import role_call, RoleCallError
from app.core.call_costs import summarize_costs


def collect_outcomes(probes, registry, client, prices, *, checkpoint_callback=None):
    summarize_costs([], prices)
    seen, patients = set(), {}
    for probe in probes:
        key = (probe["patient_id"], probe["decision_id"])
        if key in seen or patients.get(probe["patient_id"], probe["split"]) != probe["split"]:
            raise ValueError("Duplicate probe or patient crossing splits")
        seen.add(key)
        patients[probe["patient_id"]] = probe["split"]
    rows = []
    agents = [a for a in registry.snapshot()["agents"] if a["role"] == "specialty"]
    # Group probes by model to avoid repeatedly swapping large models.
    for agent, probe in ((a, p) for a in agents for p in probes):
        if probe["split"] not in {"train", "validation", "test"}:
            raise ValueError("Explicit split required")
        labels = probe["expected_diagnoses"]
        catalog = probe.get("diagnosis_catalog")
        if catalog is not None and (not isinstance(catalog, list) or not catalog or len(set(catalog)) != len(catalog)
                or any(not isinstance(x, str) or not x.strip() or len(x) > 80 for x in catalog)):
            raise ValueError("Invalid shared probe diagnosis catalog")
        if not isinstance(labels, list) or not labels or any(not isinstance(s, str) or not s.strip() for s in labels):
            raise ValueError("Expected labels required for offline scoring")
        # Whitelist observed fields to prevent accidentally sending label/source fields.
        obs = {k: probe["observation"][k] for k in ("chief_complaint", "current_symptoms", "objective_findings", "history", "longitudinal_memory")
               if k in probe["observation"]}
        audit, answer = [], None
        def validate(raw):
            result = json.loads(raw)
            if set(result) != {"diagnosis", "rationale"} or any(not isinstance(v, str) or not v.strip() for v in result.values()):
                raise ValueError("Probe requires diagnosis and rationale")
            if len(result["diagnosis"]) > 80 or len(result["rationale"]) > 160:
                raise ValueError("Probe response exceeds bounded schema")
            if catalog is not None and result["diagnosis"] not in catalog:
                raise ValueError("Probe diagnosis outside shared catalog")
            return result
        try:
            answer = role_call(client, role="specialty", model=agent["model"],
                system="Fictional offline assessment probe. Use only supplied observations. Return a concise JSON diagnosis (at most 80 characters) and rationale (one sentence, at most 160 characters); say unresolved when evidence is insufficient.",
                payload={"department": agent["department"], "observation": obs, **({"diagnosis_catalog": catalog} if catalog else {})}, audit=audit, validate=validate,
                schema={"type": "object", "properties": {"diagnosis": {"type": "string", "minLength": 1, "maxLength": 80, **({"enum": catalog} if catalog else {})},
                        "rationale": {"type": "string", "minLength": 1, "maxLength": 160}},
                        "required": ["diagnosis", "rationale"], "additionalProperties": False})
        except RoleCallError:
            pass
        norm = lambda s: " ".join(s.casefold().split())
        cost = summarize_costs(audit, prices)
        rows.append({"patient_id": probe["patient_id"], "decision_id": probe["decision_id"], "split": probe["split"],
                     "agent_id": agent["agent_id"], "model": agent["model"], "version": agent["version"],
                     "observation": obs, "correct": bool(answer and norm(answer["diagnosis"]) in {norm(s) for s in labels}),
                     "cost": cost["total_cost"], "latency_seconds": audit[-1]["latency_seconds"],
                     "answer": answer, "audit": audit, "scope": "single_assessment_probe_not_full_trajectory"})
        if checkpoint_callback is not None:
            checkpoint_callback(rows)
    return rows
