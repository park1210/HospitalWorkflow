"""Specialty routing baselines.

Routers never receive evaluation gold labels.
"""

import json
import math
import hashlib
from copy import deepcopy

from app.llm.role_call import role_call, RoleCallError, ContractValidationError


class LLMRouter:

    def __init__(
        self,
        client,
        model,
        *,
        use_memory=False,
    ):
        self.client = client
        self.model = model
        self.use_memory = use_memory

    def select(
        self,
        observation,
        candidate_departments,
        *,
        audit,
        cache=None,
    ):
        if not candidate_departments:
            return {
                "router": (
                    "MemoryAwareLLMRouter"
                    if self.use_memory
                    else "LLMRouter"
                ),
                "status": "unavailable",
                "candidate_departments": [],
                "scope": "primary_specialty_selection",
                "score_semantics": "LLM-generated routing scores; not calibrated probabilities",
                "selected_specialty": None,
                "specialty_scores": {},
                "rationale": (
                    "No registered specialty candidates"
                ),
            }

        current_state = {
            "chief_complaint":
                observation.get(
                    "chief_complaint",
                    "",
                ),
            "current_symptoms":
                observation.get(
                    "current_symptoms",
                    [],
                ),
            "vital_signs":
                observation.get(
                    "vital_signs",
                    {},
                ),
            "history":
                observation.get(
                    "history",
                    [],
                ),
            "objective_findings":
                observation.get(
                    "objective_findings",
                    [],
                ),
        }

        payload = {
            "current_state":
                current_state,
            "candidate_specialties":
                list(
                    candidate_departments
                ),
        }

        if self.use_memory:
            payload[
                "retrieved_memory"
            ] = [
                {
                    "memory_id":
                        row.get(
                            "memory_id"
                        ),
                    "kind":
                        row.get(
                            "kind"
                        ),
                    "text":
                        row.get(
                            "text"
                        ),
                    "available_at":
                        row.get(
                            "available_at"
                        ),
                    "retrieval_score":
                        row.get(
                            "retrieval_score"
                        ),
                }
                for row
                in observation.get(
                    "longitudinal_memory",
                    {},
                ).get(
                    "records",
                    [],
                )
                if row.get(
                    "status_as_of_visit"
                )
                != "superseded"
            ]

        payload[
            "instruction"
        ] = (
            "Select the single most appropriate specialty "
            "for the CURRENT presentation. "
            "Historical information is contextual only. "
            "Do not route based on an unrelated old diagnosis. "
            "Return one JSON object with selected_specialty, "
            "scores, and rationale. "
            "scores are routing scores, not probabilities. "
            "Include exactly every candidate specialty as a scores key. Each value MUST be a JSON number "
            "from 0.0 to 1.0 inclusive (example: 0.7), never a percentage like 70, a string, null, or boolean. "
            "The scores do not need to sum to one. selected_specialty must be a candidate label."
        )

        schema = {
            "type": "object",
            "properties": {
                "selected_specialty": {
                    "type": "string",
                    "enum":
                        list(
                            candidate_departments
                        ),
                },
                "scores": {
                    "type": "object",
                    "properties": {department: {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    } for department in candidate_departments},
                    "required": list(candidate_departments),
                    "additionalProperties": False,
                },
                "rationale": {
                    "type": "string",
                    "maxLength": 300,
                },
            },
            "required": [
                "selected_specialty",
                "scores",
                "rationale",
            ],
            "additionalProperties": False,
        }

        system = (
            "You are a hospital specialty routing agent. "
            "Your job is routing, not diagnosis. "
            "Choose the specialty that should primarily evaluate "
            "the patient's current clinical presentation. "
            "Use only the supplied current state"
            + (
                " and retrieved longitudinal memory."
                if self.use_memory
                else "."
            )
            + " Do not use or infer hidden evaluation labels."
        )

        def validate(raw):
            row = json.loads(
                raw
            )

            if (
                not isinstance(row, dict)
                or set(row) != {"selected_specialty", "scores", "rationale"}
                or row.get(
                    "selected_specialty"
                )
                not in candidate_departments
            ):
                raise ValueError(
                    "Invalid selected specialty"
                )

            scores = row.get(
                "scores",
                {},
            )

            if not isinstance(
                scores,
                dict,
            ):
                raise ValueError(
                    "scores must be an object"
                )

            normalized_scores = {}
            if set(scores) != set(candidate_departments):
                raise ValueError("scores must cover exactly the candidate specialties")

            for department in (
                candidate_departments
            ):
                value = scores.get(
                    department,
                    0.0,
                )

                if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                    raise ContractValidationError("Routing scores must be finite numbers between zero and one",
                        code="routing_score_contract", field="scores." + department, value=value)

                normalized_scores[
                    department
                ] = float(
                    value
                )

            rationale = row.get(
                "rationale",
                "",
            )

            if (
                not isinstance(
                    rationale,
                    str,
                )
                or not rationale.strip()
                or len(rationale) > 300
            ):
                raise ValueError(
                    "Missing routing rationale"
                )

            return {
                "selected_specialty":
                    row[
                        "selected_specialty"
                    ],
                "specialty_scores":
                    normalized_scores,
                "rationale":
                    rationale.strip(),
            }

        fingerprint = hashlib.sha256(json.dumps(
            [self.model, self.use_memory, system, schema, payload], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if cache is not None and fingerprint in cache:
            return {**deepcopy(cache[fingerprint]), "cache_hit": True}
        try:
            result = role_call(
                self.client, role="router", model=self.model, system=system,
                payload=payload, audit=audit, validate=validate, schema=schema,
                repair_codes=("routing_score_contract",))
        except RoleCallError:
            if audit:
                audit[-1]["routing_result"] = {
                    "router": "MemoryAwareLLMRouter" if self.use_memory else "LLMRouter",
                    "status": "failed", "candidate_departments": list(candidate_departments),
                    "selected_specialty": None, "specialty_scores": {},
                    "rationale": "Router call did not produce a validated result; no fallback.",
                    "reason": audit[-1].get("failure_category"),
                    "scope": "primary_specialty_selection",
                    "score_semantics": "LLM-generated routing scores; not calibrated probabilities"}
            raise

        routing_result = {
            "router": (
                "MemoryAwareLLMRouter"
                if self.use_memory
                else "LLMRouter"
            ),
            "status":
                "available",
            "candidate_departments":
                list(
                    candidate_departments
                ),
            "selected_specialty":
                result[
                    "selected_specialty"
                ],
            "specialty_scores":
                result[
                    "specialty_scores"
                ],
            "rationale":
                result[
                    "rationale"
                ],
            "scope":
                "primary_specialty_selection",
            "score_semantics": "LLM-generated routing scores; not calibrated probabilities",
            "cache_hit": False,
            "input_sha256": fingerprint,
        }
        if audit:
            audit[-1]["routing_result"] = deepcopy(routing_result)
        if cache is not None:
            cache[fingerprint] = deepcopy(routing_result)
        return routing_result
