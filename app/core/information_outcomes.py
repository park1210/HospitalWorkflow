
"""Auditable finite outcome model for cost-free Bayesian VoI.

Schema v1:
    Supports legacy cost_weights and action costs.

Schema v2:
    Requires cost-free inputs (no cost_weights or action.cost).

Both schemas are normalized internally to the legacy-compatible
structure so existing HospitalWorkflow components remain usable.

Money, minutes and tokens are never used by the VoI planner.
"""

from copy import deepcopy
import hashlib
import json
import math

from app.core.diagnostic_belief import (
    distribution,
    posterior,
    validation_utility,
)
from app.utils.department_catalog import SUPPORTED_DEPARTMENTS


def normalized(text):
    return " ".join(str(text).casefold().split())


class InformationOutcomes:
    def __init__(self, artifact):
        if not isinstance(artifact, dict):
            raise ValueError("VoI artifact must be a dictionary")

        # Preserve original input independently of internal
        # compatibility normalization.
        source = deepcopy(artifact)
        artifact = deepcopy(artifact)

        schema_version = artifact.get("schema_version")

        if type(schema_version) is not int or schema_version not in (1, 2):
            raise ValueError("Unsupported VoI schema version")

        if (
            artifact.get("terminal_utility") is None
            and isinstance(artifact.get("diagnoses"), dict)
            and artifact["diagnoses"]
        ):
            artifact["terminal_utility"] = validation_utility(
                artifact["diagnoses"]
            )
            provenance = artifact.get("provenance")
            if isinstance(provenance, dict):
                provenance["utility_scope"] = (
                    "algorithm_validation_only"
                )

        artifact.setdefault("stop_probability", 0.95)
        artifact.setdefault("horizon", 1)

        # ---------------------------------------------------------
        # Schema compatibility
        # ---------------------------------------------------------

        if schema_version == 1:
            required = {
                "schema_version",
                "model_id",
                "revision",
                "provenance",
                "diagnoses",
                "prior",
                "terminal_utility",
                "cost_weights",
                "stop_probability",
                "horizon",
                "actions",
            }

            if set(artifact) != required:
                raise ValueError("Invalid VoI v1 model fields")

        else:
            required = {
                "schema_version",
                "model_id",
                "revision",
                "provenance",
                "diagnoses",
                "prior",
                "terminal_utility",
                "stop_probability",
                "horizon",
                "actions",
            }

            if set(artifact) != required:
                raise ValueError(
                    "Invalid VoI v2 fields: cost_weights "
                    "must not appear"
                )

            if not isinstance(artifact["actions"], list):
                raise ValueError(
                    "VoI v2 actions must be a list"
                )

            for action in artifact["actions"]:
                if not isinstance(action, dict):
                    raise ValueError(
                        "VoI v2 action must be a dictionary"
                    )
                if "cost" in action:
                    raise ValueError(
                        "VoI v2 actions must not contain cost"
                    )

            # Internal compatibility representation.
            # These fields are placeholders only.
            artifact["schema_version"] = 1
            artifact["cost_weights"] = {
                "money": 0,
                "minutes": 0,
                "tokens": 0,
            }

            for action in artifact["actions"]:
                action["cost"] = {
                    "money": 0,
                    "minutes": 0,
                    "tokens": 0,
                }

            provenance = artifact.get("provenance")
            if isinstance(provenance, dict):
                provenance["cost_free_schema_source"] = 2

        # ---------------------------------------------------------
        # Model identity
        # ---------------------------------------------------------

        for key in ("model_id", "revision"):
            if (
                not isinstance(artifact[key], str)
                or not artifact[key].strip()
            ):
                raise ValueError(
                    "Explicit VoI model identity/version required"
                )

        # ---------------------------------------------------------
        # Provenance validation
        # ---------------------------------------------------------

        provenance = artifact["provenance"]

        if (
            not isinstance(provenance, dict)
            or type(provenance.get("synthetic")) is not bool
            or provenance.get("review_status")
            not in {"unreviewed", "expert_reviewed"}
            or not provenance.get("assumptions")
        ):
            raise ValueError(
                "VoI provenance and assumptions required"
            )

        if (
            provenance["review_status"] == "expert_reviewed"
            and not all(
                provenance.get(k)
                for k in ("reviewer", "review_reference")
            )
        ):
            raise ValueError(
                "Expert review requires reviewer and "
                "review reference"
            )

        patients = provenance.get("training_patients", [])

        if (
            not isinstance(patients, list)
            or any(
                not isinstance(p, str) or not p
                for p in patients
            )
            or len(set(patients)) != len(patients)
        ):
            raise ValueError(
                "Training patient IDs must be unique strings"
            )

        # ---------------------------------------------------------
        # Diagnosis universe
        # ---------------------------------------------------------

        diagnoses = artifact["diagnoses"]

        if (
            not isinstance(diagnoses, dict)
            or not 2 <= len(diagnoses) <= 32
            or any(
                not isinstance(d, str)
                or not d.strip()
                or department not in SUPPORTED_DEPARTMENTS
                for d, department in diagnoses.items()
            )
        ):
            raise ValueError(
                "Need 2..32 diagnosis labels "
                "and canonical departments"
            )

        distribution(artifact["prior"], diagnoses)

        # ---------------------------------------------------------
        # Terminal utility
        # ---------------------------------------------------------

        utility = artifact["terminal_utility"]

        if (
            not isinstance(utility, dict)
            or set(utility) != set(diagnoses)
            or any(
                not isinstance(row, dict)
                or set(row) != set(diagnoses)
                or any(
                    type(v) not in (float, int)
                    or not math.isfinite(v)
                    for v in row.values()
                )
                for row in utility.values()
            )
        ):
            raise ValueError(
                "Terminal utilities must specify every "
                "choice/true-diagnosis pair"
            )

        # ---------------------------------------------------------
        # Legacy compatibility cost validation
        # ---------------------------------------------------------

        weights = artifact["cost_weights"]

        if (
            not isinstance(weights, dict)
            or set(weights) != {"money", "minutes", "tokens"}
            or any(
                type(v) not in (int, float)
                or not math.isfinite(v)
                or v < 0
                for v in weights.values()
            )
        ):
            raise ValueError(
                "Cost conversion weights must be "
                "finite nonnegative"
            )

        # Cost fields are validated for backwards compatibility
        # but never used in action selection.

        # ---------------------------------------------------------
        # Horizon validation
        # ---------------------------------------------------------

        threshold = artifact["stop_probability"]

        if (
            type(threshold) not in (int, float)
            or not math.isfinite(threshold)
            or not 0.5 < threshold <= 1
        ):
            raise ValueError(
                "Stop threshold must be > 0.5 and <= 1"
            )

        if (
            type(artifact["horizon"]) is not int
            or not 1 <= artifact["horizon"] <= 3
        ):
            raise ValueError(
                "Planning horizon must be 1..3"
            )

        # ---------------------------------------------------------
        # Action validation
        # ---------------------------------------------------------

        actions = artifact["actions"]

        if (
            not isinstance(actions, list)
            or not 1 <= len(actions) <= 12
        ):
            raise ValueError(
                "Provide 1..12 information actions"
            )

        ids = set()
        bindings = set()
        signatures = set()

        sources = {
            "request_test": "objective_findings",
            "ask_patient": "history",
            "consult_specialty": "consults",
            "retrieve_memory": "memory",
        }

        for action in actions:
            if (
                not isinstance(action, dict)
                or set(action)
                != {"id", "type", "target", "cost", "outcomes"}
                or action.get("type") not in sources
            ):
                raise ValueError(
                    "Invalid information action"
                )

            if any(
                not isinstance(action[k], str)
                or not action[k].strip()
                for k in ("id", "target")
            ):
                raise ValueError(
                    "Action ID and target required"
                )

            if (
                action["id"] in ids
                or (action["type"], action["target"])
                in bindings
            ):
                raise ValueError(
                    "Duplicate action ID or binding"
                )

            ids.add(action["id"])
            bindings.add(
                (action["type"], action["target"])
            )

            if (
                action["type"] == "consult_specialty"
                and action["target"]
                not in SUPPORTED_DEPARTMENTS
            ):
                raise ValueError(
                    "Consult target must be canonical"
                )

            if (
                action["type"] == "ask_patient"
                and not action["target"].endswith(("?", "？"))
            ):
                raise ValueError(
                    "Question target must end with ?"
                )

            if (
                action["type"] == "retrieve_memory"
                and action["target"] != "longitudinal"
            ):
                raise ValueError(
                    "Only longitudinal memory acquisition "
                    "is supported"
                )

            action_cost = action["cost"]

            if (
                not isinstance(action_cost, dict)
                or set(action_cost) != set(weights)
                or any(
                    type(v) not in (int, float)
                    or not math.isfinite(v)
                    or v < 0
                    for v in action_cost.values()
                )
            ):
                raise ValueError(
                    "Action costs must explicitly include "
                    "money/minutes/tokens"
                )

            outcomes = action["outcomes"]

            if (
                not isinstance(outcomes, list)
                or not 2 <= len(outcomes) <= 8
            ):
                raise ValueError(
                    "Need 2..8 categorical outcomes "
                    "per action"
                )

            outcome_ids = set()

            for outcome in outcomes:
                if (
                    not isinstance(outcome, dict)
                    or set(outcome)
                    != {
                        "id",
                        "likelihood",
                        "observation",
                        "supports_diagnoses",
                    }
                ):
                    raise ValueError(
                        "Invalid outcome fields"
                    )

                if (
                    not isinstance(outcome["id"], str)
                    or not outcome["id"]
                    or outcome["id"] in outcome_ids
                ):
                    raise ValueError(
                        "Unique outcome IDs required"
                    )

                outcome_ids.add(outcome["id"])

                likelihood = outcome["likelihood"]

                if (
                    not isinstance(likelihood, dict)
                    or set(likelihood) != set(diagnoses)
                    or any(
                        type(p) not in (float, int)
                        or not math.isfinite(p)
                        or not 0 <= p <= 1
                        for p in likelihood.values()
                    )
                ):
                    raise ValueError(
                        "Likelihood must define "
                        "P(outcome|diagnosis,action)"
                    )

                observation = outcome["observation"]

                if (
                    not isinstance(observation, dict)
                    or set(observation)
                    != {"source", "text"}
                    or observation["source"]
                    != sources[action["type"]]
                    or not isinstance(
                        observation["text"], str
                    )
                    or not observation["text"].strip()
                ):
                    raise ValueError(
                        "Outcome observation must match "
                        "the action's released source"
                    )

                signature = (
                    observation["source"],
                    normalized(observation["text"]),
                )

                if signature in signatures:
                    raise ValueError(
                        "Observation text must not count "
                        "as two independent outcomes"
                    )

                signatures.add(signature)

                support = outcome["supports_diagnoses"]

                if (
                    not isinstance(support, list)
                    or not set(support) <= set(diagnoses)
                    or (
                        support
                        and observation["source"]
                        != "objective_findings"
                    )
                ):
                    raise ValueError(
                        "Only explicit current objective "
                        "outcomes may support finalization"
                    )

            for diagnosis in diagnoses:
                total = sum(
                    outcome["likelihood"][diagnosis]
                    for outcome in outcomes
                )

                if not math.isclose(
                    total,
                    1.0,
                    abs_tol=1e-9,
                    rel_tol=0,
                ):
                    raise ValueError(
                        "Outcome likelihoods must sum "
                        "to one for each diagnosis/action"
                    )

        # ---------------------------------------------------------
        # Save validated model
        # ---------------------------------------------------------

        self.source_schema_version = schema_version

        self.artifact = deepcopy(artifact)

        # Preserve the identity of the original supplied model.
        self.fingerprint = hashlib.sha256(
            json.dumps(
                source,
                sort_keys=True,
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()

    def observe(self, observation):
        """Update diagnosis belief from released observations."""

        belief = dict(self.artifact["prior"])
        matched = []

        for action in self.artifact["actions"]:
            kind = action["type"]
            target = action["target"]

            texts = []

            if kind == "request_test":
                texts = [
                    t
                    for t in observation.get(
                        "objective_findings", []
                    )
                    if str(t).startswith(target + ":")
                ]

            elif kind == "ask_patient":
                texts = [
                    record.get("answer", "")
                    for record in observation.get(
                        "history", []
                    )
                    if (
                        record.get("question") == target
                        and record.get("answer_status")
                        != "unknown"
                    )
                ]

            elif kind == "consult_specialty":
                texts = [
                    record.get("opinion", "")
                    for record in observation.get(
                        "consults", []
                    )
                    if record.get("department") == target
                ]

            elif kind == "retrieve_memory":
                texts = [
                    record["text"]
                    for record in observation.get(
                        "longitudinal_memory", {}
                    ).get("records", [])
                    if (
                        record.get("status_as_of_visit")
                        != "superseded"
                    )
                ]

            normalized_texts = {
                normalized(text)
                for text in texts
            }
            # Opt-in replay adapter: bins are computed using frozen TRAIN-only
            # thresholds; original source evidence stays in the released text.
            if self.artifact["provenance"].get("observation_encoding") == "replay_bins_v1":
                normalized_texts = set()
                for text in texts:
                    raw = str(text)
                    if kind == "request_test":
                        raw = raw[len(target) + 1:].strip()
                    try:
                        encoded = json.loads(raw)
                        outcome_id = encoded["replay_bin"]
                    except (ValueError, KeyError, TypeError) as exc:
                        raise ValueError("Invalid released replay bin") from exc
                    outcome = next((o for o in action["outcomes"] if o["id"] == outcome_id), None)
                    if outcome is None:
                        raise ValueError("Unknown released replay bin")
                    normalized_texts.add(normalized(outcome["observation"]["text"]))

            found = [
                outcome
                for outcome in action["outcomes"]
                if normalized(
                    outcome["observation"]["text"]
                ) in normalized_texts
            ]

            if len(found) > 1:
                raise ValueError(
                    "Conflicting outcome observations; "
                    "conditional-independent model "
                    "not applicable"
                )

            if texts and not found:
                raise ValueError(
                    "Released outcome is outside "
                    "the supplied categorical model"
                )

            if found:
                belief, mass = posterior(
                    belief,
                    found[0]["likelihood"],
                )

                matched.append({
                    "action_id": action["id"],
                    "outcome_id": found[0]["id"],
                    "predictive_probability": mass,
                    "observation": deepcopy(
                        found[0]["observation"]
                    ),
                    "supports_diagnoses":
                        found[0]["supports_diagnoses"],
                })

        return belief, matched
