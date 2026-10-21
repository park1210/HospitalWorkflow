"""Explicit model bindings and inexpensive consultation-menu baselines."""
from copy import deepcopy
import hashlib
import json
import re

from app.utils.department_catalog import SUPPORTED_DEPARTMENTS


class AgentRegistry:
    def __init__(self, manifest, utility_artifact=None):
        if set(manifest) != {"schema_version", "agents"} or manifest["schema_version"] != 1:
            raise ValueError("Invalid agent registry schema")
        if not isinstance(manifest["agents"], list) or not manifest["agents"]:
            raise ValueError("Registry needs agents")
        self._manifest = deepcopy(manifest)
        ids, bindings = set(), set()
        for agent in self._manifest["agents"]:
            if set(agent) != {"agent_id", "role", "department", "model", "version", "keywords"}:
                raise ValueError("Invalid agent fields")
            if any(not isinstance(agent[k], str) or not agent[k].strip()
                   for k in ("agent_id", "role", "model", "version")):
                raise ValueError("Agent identity/model/version must be nonempty strings")
            if agent["role"] not in {"er", "specialty"}:
                raise ValueError("Unknown agent role")
            if (agent["role"] == "er" and agent["department"] != "") or (
                agent["role"] == "specialty" and agent["department"] not in SUPPORTED_DEPARTMENTS):
                raise ValueError("Use canonical specialty department or empty ER department")
            if not isinstance(agent["keywords"], list) or any(not isinstance(x, str) or not x.strip() for x in agent["keywords"]):
                raise ValueError("keywords must be nonempty strings")
            binding = (agent["role"], agent["department"])
            if agent["agent_id"] in ids or binding in bindings:
                raise ValueError("Duplicate agent or role/department binding")
            ids.add(agent["agent_id"])
            bindings.add(binding)
        if ("er", "") not in bindings:
            raise ValueError("Exactly one ER binding is required")
        from app.core.routing_utility import RoutingUtility
        self.utility = RoutingUtility(utility_artifact, self) if utility_artifact is not None else None

    def snapshot(self):
        return deepcopy(self._manifest)

    def get(self, role, department=""):
        for agent in self._manifest["agents"]:
            if agent["role"] == role and agent["department"] == department:
                return deepcopy(agent)
        raise ValueError(f"No registered agent for {role}/{department}")

    def select_specialty(self, current_state, retrieved_memory, departments, *, router="rule_similarity", seed=0):
        """Common primary-router interface; unimplemented routers never masquerade as baselines."""
        if router not in {"rule_similarity", "llm", "memory_aware_llm"}:
            raise ValueError("Unknown specialty router")
        if router != "rule_similarity":
            return {"router": router, "status": "unavailable", "reason": "router_not_implemented",
                    "specialty_scores": {}, "selected_specialty": None}
        observed = deepcopy(current_state)
        observed["longitudinal_memory"] = deepcopy(retrieved_memory)
        result = self.route(observed, departments, mode="adaptive", seed=seed)
        return {**result, "router": "RuleSimilarityRouter", "status": "available",
                "score_semantics": "uncalibrated similarity-weighted outcome score or keyword baseline",
                "scope": "primary_specialty_selection"}

    def route(self, observation, departments, *, mode="llm", seed=0):
        if mode not in {"llm", "er_only", "rule", "random", "adaptive"}:
            raise ValueError("Unknown routing baseline")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("Routing seed must be an integer")
        bound = {a["department"] for a in self._manifest["agents"] if a["role"] == "specialty"}
        candidates = sorted(set(departments) & bound)
        # Only explicit observed content; no source-case or evaluation fields.
        texts = [observation.get("chief_complaint", ""), *observation.get("current_symptoms", []),
                 *observation.get("objective_findings", [])]
        texts += [q.get("answer", "") for q in observation.get("history", []) if q.get("answer_status") != "unknown"]
        texts += [r["text"] for r in observation.get("longitudinal_memory", {}).get("records", [])
                  if r.get("status_as_of_visit") != "superseded"]
        tokens = set(re.findall(r"\w+", " ".join(str(t) for t in texts).casefold()))
        scores = {d: sum(set(re.findall(r"\w+", word.casefold())) <= tokens
                         for word in self.get("specialty", d)["keywords"]) for d in candidates}
        specialty_scores = dict(scores)
        selected = candidates
        estimates = {}
        reason = "LLM may choose among registered and currently available departments."
        if mode == "er_only":
            selected, reason = [], "ER-only baseline disables consultations."
        elif mode == "rule":
            ranked = sorted(candidates, key=lambda d: (-scores[d], d))
            selected = ranked[:1] if ranked and scores[ranked[0]] > 0 else []
            reason = "Highest configured keyword overlap; canonical label breaks ties; no positive match means ER only."
        elif mode == "random":
            digest = hashlib.sha256(json.dumps([seed, sorted(tokens), candidates], ensure_ascii=False).encode()).hexdigest()
            selected = [candidates[int(digest, 16) % len(candidates)]] if candidates else []
            reason = "Seeded hash selects one available department from the observed token set."
        elif mode == "adaptive":
            estimates = {d: self.utility.score(observation, self.get("specialty", d)) if self.utility else None
                         for d in candidates}
            supported = [d for d in candidates if estimates[d] is not None]
            if len(supported) == len(candidates):
                specialty_scores = {d: estimates[d]["score"] for d in candidates}
                selected = sorted(supported, key=lambda d: (-specialty_scores[d], d))[:1]
                reason = "Maximum context-and-memory specialty score; cost/latency do not affect selection."
            else:
                selected = sorted(candidates, key=lambda d: (-scores[d], d))[:1]
                reason = "Incomplete fitted coverage: existing keyword score argmax; canonical label breaks ties."
        return {"mode": mode, "seed": seed, "candidate_departments": candidates,
                "specialty_scores": specialty_scores, "selected_specialty": selected[0] if len(selected) == 1 else None,
                "utility_estimates": estimates, "utility_artifact_sha256": self.utility.fingerprint if self.utility else None,
                "allowed_departments": selected, "keyword_scores": scores, "rationale": reason,
                "scope": "consultation_menu; physician still decides whether and when to consult"}
