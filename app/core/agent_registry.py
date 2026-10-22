
"""Explicit model bindings and specialty consultation routing.

Routing decisions and available consultation candidates
are represented separately.

The rule_similarity primary router uses the rule baseline.
The adaptive router abstains without sufficient fitted evidence.
"""

from copy import deepcopy
import hashlib
import json
import math
import re

from app.utils.department_catalog import SUPPORTED_DEPARTMENTS


class AgentRegistry:
    def __init__(self, manifest, utility_artifact=None):
        if (
            not isinstance(manifest, dict)
            or set(manifest) != {"schema_version", "agents"}
            or manifest["schema_version"] != 1
        ):
            raise ValueError("Invalid agent registry schema")

        if not isinstance(manifest["agents"], list) or not manifest["agents"]:
            raise ValueError("Registry needs agents")

        self._manifest = deepcopy(manifest)
        ids = set()
        bindings = set()

        for agent in self._manifest["agents"]:
            required = {
                "agent_id", "role", "department",
                "model", "version", "keywords",
            }
            if not isinstance(agent, dict) or set(agent) != required:
                raise ValueError("Invalid agent fields")

            if any(
                not isinstance(agent[key], str) or not agent[key].strip()
                for key in ("agent_id", "role", "model", "version")
            ):
                raise ValueError(
                    "Agent identity/model/version must be nonempty strings"
                )

            if agent["role"] not in {"er", "specialty"}:
                raise ValueError("Unknown agent role")

            if (
                (agent["role"] == "er" and agent["department"] != "")
                or (
                    agent["role"] == "specialty"
                    and agent["department"] not in SUPPORTED_DEPARTMENTS
                )
            ):
                raise ValueError(
                    "Use canonical specialty department or empty ER department"
                )

            if (
                not isinstance(agent["keywords"], list)
                or any(
                    not isinstance(word, str) or not word.strip()
                    for word in agent["keywords"]
                )
            ):
                raise ValueError("keywords must be nonempty strings")

            binding = (agent["role"], agent["department"])

            if agent["agent_id"] in ids or binding in bindings:
                raise ValueError(
                    "Duplicate agent or role/department binding"
                )

            ids.add(agent["agent_id"])
            bindings.add(binding)

        if ("er", "") not in bindings:
            raise ValueError("Exactly one ER binding is required")

        from app.core.routing_utility import RoutingUtility

        self.utility = (
            RoutingUtility(utility_artifact, self)
            if utility_artifact is not None
            else None
        )

    def snapshot(self):
        return deepcopy(self._manifest)

    def get(self, role, department=""):
        for agent in self._manifest["agents"]:
            if agent["role"] == role and agent["department"] == department:
                return deepcopy(agent)

        raise ValueError(
            f"No registered agent for {role}/{department}"
        )

    def select_specialty(
        self,
        current_state,
        retrieved_memory,
        departments,
        *,
        router="rule_similarity",
        seed=0,
    ):
        """Select the primary specialty using the requested router."""
        if router not in {
            "rule_similarity", "adaptive", "llm", "memory_aware_llm"
        }:
            raise ValueError("Unknown specialty router")

        if router not in {"rule_similarity", "adaptive"}:
            return {
                "router": router,
                "status": "unavailable",
                "reason": "router_not_implemented",
                "decision_status": "unavailable",
                "candidate_departments": list(departments),
                "allowed_departments": list(departments),
                "specialty_scores": {},
                "selected_specialty": None,
            }

        observed = deepcopy(current_state)
        observed["longitudinal_memory"] = deepcopy(retrieved_memory)

        # IMPORTANT:
        # RuleSimilarityRouter is a rule baseline,
        # not a fitted adaptive utility router.
        result = self.route(
            observed,
            departments,
            mode="adaptive" if router == "adaptive" else "rule",
            seed=seed,
        )

        return {
            **result,
            "router": "AdaptiveAccuracyRouter" if router == "adaptive" else "RuleSimilarityRouter",
            "status": (
                "available"
                if result["decision_status"] == "selected"
                else result["decision_status"]
            ),
            "score_semantics": (
                "uncalibrated similarity-weighted correctness" if router == "adaptive"
                else "keyword overlap score; not a calibrated probability"
            ),
            "scope": "primary_specialty_selection",
        }

    def route(
        self,
        observation,
        departments,
        *,
        mode="llm",
        seed=0,
    ):
        """Return routing decision with explicit decision_status.

        selected: a router selected a specialty.
        abstained: evidence was insufficient for selection.
        unavailable: no registered specialty candidate.
        delegated: selection is delegated to another model.
        disabled: ER-only mode disables consultation.
        """
        if mode not in {
            "llm", "er_only", "rule", "random", "adaptive"
        }:
            raise ValueError("Unknown routing baseline")

        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("Routing seed must be an integer")

        if not isinstance(observation, dict):
            raise ValueError("Observation must be a dictionary")

        bound = {
            agent["department"]
            for agent in self._manifest["agents"]
            if agent["role"] == "specialty"
        }
        candidates = sorted(set(departments) & bound)

        texts = [
            observation.get("chief_complaint", ""),
            *observation.get("current_symptoms", []),
            *observation.get("objective_findings", []),
        ]

        texts += [
            row.get("answer", "")
            for row in observation.get("history", [])
            if (
                isinstance(row, dict)
                and row.get("answer_status") != "unknown"
            )
        ]

        texts += [
            row.get("text", "")
            for row in observation.get(
                "longitudinal_memory", {}
            ).get("records", [])
            if (
                isinstance(row, dict)
                and row.get("status_as_of_visit") != "superseded"
            )
        ]

        tokens = set(
            re.findall(
                r"\w+",
                " ".join(str(item) for item in texts).casefold(),
            )
        )

        scores = {}
        for department in candidates:
            agent = self.get("specialty", department)

            scores[department] = sum(
                bool(re.findall(r"\w+", keyword.casefold()))
                and set(
                    re.findall(r"\w+", keyword.casefold())
                ) <= tokens
                for keyword in agent["keywords"]
            )

        specialty_scores = dict(scores)
        allowed = list(candidates)
        selected_specialty = None
        tied_departments = []
        estimates = {}

        if not candidates:
            decision_status = "unavailable"
            reason = "No registered specialty candidates."

        elif mode == "er_only":
            allowed = []
            decision_status = "disabled"
            reason = "ER-only baseline disables consultations."

        elif mode == "llm":
            decision_status = "delegated"
            reason = (
                "Registered specialties are available; "
                "an LLM must make the selection."
            )

        elif mode == "rule":
            ranked = sorted(
                candidates,
                key=lambda department: (
                    -scores[department],
                    department,
                ),
            )

            if ranked and scores[ranked[0]] > 0:
                selected_specialty = ranked[0]
                allowed = [selected_specialty]
                decision_status = "selected"
            else:
                allowed = []
                decision_status = "abstained"

            reason = (
                "Highest configured keyword overlap. "
                "No positive match means abstention."
            )

        elif mode == "random":
            digest = hashlib.sha256(
                json.dumps(
                    [seed, sorted(tokens), candidates],
                    ensure_ascii=False,
                ).encode()
            ).hexdigest()

            selected_specialty = candidates[
                int(digest, 16) % len(candidates)
            ]
            allowed = [selected_specialty]
            decision_status = "selected"
            reason = (
                "Seeded hash selects one available specialty."
            )

        elif mode == "adaptive":
            estimates = {
                department: (
                    self.utility.score(
                        observation,
                        self.get("specialty", department),
                    )
                    if self.utility is not None
                    else None
                )
                for department in candidates
            }

            supported = [
                department
                for department in candidates
                if estimates[department] is not None
            ]

            if len(supported) == len(candidates):
                specialty_scores = {
                    department: estimates[department]["score"]
                    for department in candidates
                }

                ranked = sorted(
                    candidates,
                    key=lambda department: (
                        -specialty_scores[department],
                        department,
                    ),
                )

                best_score = specialty_scores[ranked[0]]
                tied_departments = [d for d in ranked if math.isclose(
                    specialty_scores[d], best_score, rel_tol=0.0, abs_tol=1e-12)]
                if len(tied_departments) > 1:
                    allowed = list(candidates)
                    decision_status = "abstained"
                    reason = "Equal best estimated correctness; no evidence to prefer one specialty. Continue ER assessment."
                else:
                    selected_specialty = ranked[0]
                    allowed = [selected_specialty]
                    decision_status = "selected"
                    reason = (
                        "Selected maximum estimated utility "
                        "using similarity-weighted correctness only."
                    )
            else:
                # Keep the available menu, but do not invent
                # a decision without fitted evidence.
                allowed = list(candidates)
                selected_specialty = None
                decision_status = "abstained"
                reason = (
                    "Insufficient fitted training support. "
                    "No autonomous specialty selection."
                )

        return {
            "mode": mode,
            "seed": seed,
            "candidate_departments": candidates,
            "allowed_departments": allowed,
            "selected_specialty": selected_specialty,
            "decision_status": decision_status,
            "specialty_scores": specialty_scores,
            "tied_departments": tied_departments,
            "tie_tolerance": 1e-12,
            "utility_estimates": estimates,
            "utility_artifact_sha256": (
                self.utility.fingerprint
                if self.utility is not None
                else None
            ),
            "keyword_scores": scores,
            "rationale": reason,
            "scope": (
                "consultation_menu; physician still decides "
                "whether and when to consult"
            ),
        }
