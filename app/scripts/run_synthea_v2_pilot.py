"""Synthea v2 Memory/Router pilot.

Offline is the default.

Memory conditions:
- no_memory
- full_history_budgeted
- selective

Budgeted Full History keeps the full eligible history as its source pool,
does not use relevance scoring for selection, and provides the most recent
records that fit inside a fixed memory character budget.

Selective Memory uses the existing retrieval method and the same memory
character budget.

VoI performance is not evaluated in this script.
"""

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from app.core.agent_registry import AgentRegistry
from app.core.clinical_observation import memory_query
from app.core.longitudinal_memory import timestamp
from app.core.longitudinal_runner import run_longitudinal
from app.data.synthea_v2_adapter import convert_case


def digest(path):
    return hashlib.sha256(
        Path(path).read_bytes()
    ).hexdigest()


def recommended_ids(path):
    """Read ranked case IDs only.

    Report prose never becomes an agent input.
    """

    groups = {
        "routing": [],
        "memory": [],
    }

    section = None

    for line in Path(path).read_text(
        encoding="utf-8-sig"
    ).splitlines():

        if line.startswith("## "):
            section = (
                line[3:]
                .strip()
                .lower()
            )

        elif (
            section in groups
            and line.startswith("|")
        ):
            cells = [
                c.strip()
                for c in line
                .strip("| ")
                .split("|")
            ]

            if cells[0].isdigit():
                if (
                    int(cells[0])
                    != len(
                        groups[
                            section
                        ]
                    )
                    + 1
                    or not cells[
                        1
                    ].startswith(
                        "symptom-v1-"
                    )
                ):
                    raise ValueError(
                        "Invalid recommendation "
                        "rank or case ID"
                    )

                groups[
                    section
                ].append(
                    cells[1]
                )

    for (
        section,
        count,
    ) in (
        (
            "routing",
            10,
        ),
        (
            "memory",
            9,
        ),
    ):
        if (
            len(
                groups[
                    section
                ]
            )
            != count
            or len(
                set(
                    groups[
                        section
                    ]
                )
            )
            != count
        ):
            raise ValueError(
                f"Expected {count} unique "
                f"{section} recommendations"
            )

    return groups


class PilotBoundary:

    def __init__(
        self,
        registry,
        *,
        live=False,
        context_chars=60000,
        max_calls=16,
        max_router_calls=8,
        max_clinical_calls=8,
    ):
        self.registry = registry
        self.live = live
        self.context_chars = (
            context_chars
        )
        self.max_calls = max_calls
        self.call_limits = {"router": max_router_calls, "clinical": max_clinical_calls}
        self.call_counts = {"router": 0, "clinical": 0}

        self.traces = []
        self.calls = 0

    def chat_json(
        self,
        system,
        prompt,
        model=None,
        schema=None,
    ):
        payload = json.loads(
            prompt
        )

        is_router_call = "current_state" in payload and "candidate_specialties" in payload
        observed = payload["current_state"] if is_router_call else payload["observation"]

        forbidden = {
            "evaluation",
            "primary_specialty",
            "gold_condition_description",
            "module",
            "cause",
            "source_event_store",
            "current_symptom_provenance",
            "current_symptom_annotation",
        }

        def check(obj):
            if isinstance(
                obj,
                dict,
            ):
                assert not (
                    set(obj)
                    & forbidden
                ), (
                    "Hidden fields "
                    "in model payload"
                )

                for value in obj.values():
                    check(
                        value
                    )

            elif isinstance(
                obj,
                list,
            ):
                for value in obj:
                    check(
                        value
                    )

        check(
            payload
        )

        # Includes:
        # - system prompt
        # - serialized payload
        # - output schema
        #
        # This is only a character-based guard.
        # It is NOT an exact tokenizer/context-window guarantee.
        chars = (
            len(
                system
            )
            + len(
                prompt
            )
            + len(
                json.dumps(
                    schema,
                    ensure_ascii=False,
                )
            )
        )

        trace = {
            "observation":
                observed,
            "routing_context":
                payload.get(
                    "routing_context"
                ),
            "role": "router" if is_router_call else payload["role"],
            "model_binding":
                model,
            "memory_query":
                None if is_router_call else memory_query(
                    observed
                ),
            "input_characters":
                chars,
            "estimated_input_tokens":
                math.ceil(
                    chars / 4
                ),
            "token_estimate_method":
                (
                    "ceil(characters/4); "
                    "not a tokenizer/context guarantee"
                ),
            "context_limit_characters":
                self.context_chars,
            "candidate_actions":
                payload.get(
                    "candidate_actions"
                ),
            "leakage_keys_check":
                True,
            "requested_selector":
                None if is_router_call else "specialist_heuristic",
            "executed_selector":
                None,
        }
        if is_router_call:
            trace["candidate_specialties"] = payload["candidate_specialties"]
            trace["router_uses_memory"] = "retrieved_memory" in payload
            if "retrieved_memory" in payload:
                trace["retrieved_memory"] = payload["retrieved_memory"]

        self.traces.append(
            trace
        )

        if (
            chars
            > self.context_chars
        ):
            trace[
                "status"
            ] = (
                "context_limit_exceeded"
            )

            raise RuntimeError(
                "Context character budget exceeded; "
                "memory should already have been "
                "budgeted before this boundary"
            )

        if not self.live:
            trace[
                "status"
            ] = (
                "stopped_before_model_call"
            )

            raise RuntimeError(
                "Intentional offline boundary"
            )

        kind = "router" if is_router_call else "clinical"
        trace["request_kind"] = kind
        trace["call_counts_before"] = dict(self.call_counts)
        trace["call_limits"] = {**self.call_limits, "total": self.max_calls}
        if self.calls >= self.max_calls or self.call_counts[kind] >= self.call_limits[kind]:
            trace["limit_type"] = "total" if self.calls >= self.max_calls else kind
            trace[
                "status"
            ] = (
                "model_call_limit_exceeded"
            )

            raise RuntimeError(
                "Pilot call limit"
            )

        from app.llm.ollama_client import (
            OllamaClient,
        )

        self.calls += 1
        self.call_counts[kind] += 1

        trace[
            "status"
        ] = (
            "live_model_requested"
        )

        return OllamaClient().chat_json(
            system,
            prompt,
            model=model,
            schema=schema,
        )


def run_case(
    case,
    mode,
    manifest,
    args,
):
    registry = AgentRegistry(
        manifest
    )

    boundary = PilotBoundary(
        registry,
        live=args.live,
        context_chars=(
            args.context_chars
        ),
        max_calls=getattr(args, "max_model_calls", 16),
        max_router_calls=getattr(args, "max_router_calls", 8),
        max_clinical_calls=getattr(args, "max_clinical_calls", 8),
    )

    mode_map = {
        "no_memory":
            "none",
        "full_history_budgeted":
            "full_history",
        "selective":
            "selective",
    }

    actual_mode = (
        mode_map[
            mode
        ]
    )

    # Apply the same memory budget to both:
    #
    # - Budgeted Full History
    # - Retrieved/Selective Memory
    #
    # No Memory receives no memory budget because it retrieves no records.
    if mode in {
        "full_history_budgeted",
        "selective",
    }:
        max_memory_chars = (
            args.memory_chars
        )
    else:
        max_memory_chars = None

    report = run_longitudinal(
        [case],
        mode=actual_mode,
        top_k=args.top_k,
        memory_source="fixed",
        registry_manifest=manifest,
        routing_mode="adaptive",
        primary_router=getattr(args, "primary_router", "rule_similarity"),
        client=boundary,
        action_selector=(
            "specialist_heuristic"
        ),
        minute_limit=120,
        max_memory_chars=(
            max_memory_chars
        ),
    )

    visit = report[
        "visits"
    ][0]

    memory = visit[
        "memory_context"
    ]

    cutoff = timestamp(
        case[
            "index_encounter_start"
        ]
    )

    assert all(
        (
            r[
                "patient_id"
            ]
            == case[
                "longitudinal"
            ][
                "patient_id"
            ]
            and r[
                "visit_id"
            ]
            != case[
                "index_encounter_id"
            ]
            and timestamp(
                r[
                    "available_at"
                ]
            )
            < cutoff
        )
        for r in memory[
            "records"
        ]
    )

    first = (
        boundary.traces[
            0
        ]
        if boundary.traces
        else None
    )

    runtime = next(iter(visit["final_state"]["cases"].values()))
    primary_router = getattr(args, "primary_router", "rule_similarity")
    routing = deepcopy(runtime.get("voi_state", {}).get("primary_routing"))
    routing_result_source = "runtime" if routing is not None else "unavailable"
    # Compatibility only for old rule runs. Never invent a rule result for an LLM router.
    if routing is None and primary_router == "rule_similarity" and first and first["role"] == "specialty":
        routing = registry.select_specialty(
            first["observation"], first["observation"].get("longitudinal_memory", {}),
            [a["department"] for a in manifest["agents"] if a["role"] == "specialty"])
        routing_result_source = "legacy_rule_recomputation"

    binding = (
        registry.get(
            "specialty",
            routing[
                "selected_specialty"
            ],
        )
        if routing and routing.get("selected_specialty")
        else None
    )

    for trace in boundary.traces:
        if trace["role"] == "router":
            assert trace["model_binding"] == registry.get("er")["model"]
        elif trace["role"] == "specialty":
            # Each clinical call may follow a new routing decision in a later loop.
            executing = (trace.get("routing_context") or {}).get("executing_agent")
            assert executing and trace["model_binding"] == executing["model"]

    status = (
        boundary.traces[
            -1
        ][
            "status"
        ]
        if (
            boundary.traces
            and boundary.traces[
                -1
            ][
                "status"
            ]
            != "live_model_requested"
        )
        else report[
            "status"
        ]
    )

    runtime = next(
        iter(
            visit[
                "final_state"
            ][
                "cases"
            ].values()
        )
    )

    return {
        "initial_routing": deepcopy(runtime.get("voi_state", {}).get("initial_primary_routing")),
        "routing_history": deepcopy(runtime.get("voi_state", {}).get("primary_routing_history", [])),
        "model_call_counts": dict(boundary.call_counts),
        "model_call_limits": {**boundary.call_limits, "total": boundary.max_calls},
        "contract_repair_attempts": sum("repair_of_audit_index" in a for a in runtime.get("llm_audit", [])),
        "primary_router": primary_router,
        "routing_result_source": routing_result_source,
        "router_model": registry.get("er")["model"] if primary_router != "rule_similarity" else None,
        "specialty_boundary_reached": any(t["role"] == "specialty" for t in boundary.traces),
        "router_audit": [a for a in runtime.get("llm_audit", []) if a.get("role") == "router"],
        "case_id":
            case[
                "case_id"
            ],
        "memory_mode":
            mode,
        "status":
            status,
        "runner_status":
            report[
                "status"
            ],
        "boundary_reached":
            bool(
                first
            ),
        "expected_offline_exception":
            (
                status
                == "stopped_before_model_call"
            ),
        "actual_llm_calls":
            boundary.calls,
        "routing":
            routing,
        "binding":
            binding,
        "memory":
            memory,
        "memory_budget": {
            "max_memory_chars":
                max_memory_chars,
            "selected_count":
                memory.get(
                    "selected_count"
                ),
            "eligible_count":
                memory.get(
                    "eligible_count"
                ),
            "records_json_chars":
                memory.get(
                    "records_json_chars"
                ),
            "budget_excluded_count":
                memory.get(
                    "budget_excluded_count"
                ),
            "selection_method":
                memory.get(
                    "selection_method"
                ),
        },
        "boundary_traces":
            boundary.traces,
        "requested_selector":
            "specialist_heuristic",
        "executed_selector":
            runtime.get(
                "voi_state",
                {},
            ).get(
                "selector_status",
                {},
            ).get(
                "executed_selector"
            ),
        "failure_detail":
            visit.get(
                "failure_detail"
            ),
        "live_final_state":
            (
                visit[
                    "final_state"
                ]
                if args.live
                else None
            ),
    }


def evaluate(
    results,
    sources,
):
    for result in results:
        gold = sources[
            result[
                "case_id"
            ]
        ][
            "evaluation"
        ]

        selected = (
            (
                result[
                    "routing"
                ]
                or {}
            ).get(
                "selected_specialty"
            )
        )

        valid = (
            selected
            is not None
            and result[
                "status"
            ]
            != (
                "context_limit_exceeded"
            )
        )

        result[
            "evaluation"
        ] = {
            "gold_specialty":
                gold[
                    "primary_specialty"
                ],
            "acceptable_specialties":
                gold[
                    "acceptable_specialties"
                ],
            "gold_in_registry":
                gold[
                    "primary_specialty"
                ]
                in (
                    (
                        result[
                            "routing"
                        ]
                        or {}
                    ).get(
                        "candidate_departments",
                        [],
                    )
                ),
            "strict_correct":
                (
                    selected
                    == gold[
                        "primary_specialty"
                    ]
                    if valid
                    else None
                ),
            "acceptable_correct":
                (
                    selected
                    in gold[
                        "acceptable_specialties"
                    ]
                    if valid
                    else None
                ),
        }

    # Preserve initial routing separately even if later workflow/Router steps fail.
    for result in results:
        initial = result.get("initial_routing") or {}
        selected = initial.get("selected_specialty")
        gold = sources[result["case_id"]]["evaluation"]
        valid = initial.get("status") == "available" and selected is not None
        result["initial_routing_evaluation"] = {
            "strict_correct": selected == gold["primary_specialty"] if valid else None,
            "acceptable_correct": selected in gold["acceptable_specialties"] if valid else None}

    summaries = {}

    for mode in sorted(
        {
            r[
                "memory_mode"
            ]
            for r in results
        }
    ):
        rows = [
            r
            for r in results
            if r[
                "memory_mode"
            ]
            == mode
        ]

        valid = [
            r
            for r in rows
            if r[
                "evaluation"
            ][
                "strict_correct"
            ]
            is not None
        ]

        memory_sizes = [
            r[
                "memory_budget"
            ].get(
                "records_json_chars"
            )
            for r in rows
            if r.get(
                "memory_budget"
            )
            and r[
                "memory_budget"
            ].get(
                "records_json_chars"
            )
            is not None
        ]

        summaries[
            mode
        ] = {
            "runs":
                len(
                    rows
                ),
            "evaluated_routing_runs":
                len(
                    valid
                ),
            "statuses":
                dict(
                    Counter(
                        r[
                            "status"
                        ]
                        for r in rows
                    )
                ),
            "strict_accuracy":
                (
                    sum(
                        r[
                            "evaluation"
                        ][
                            "strict_correct"
                        ]
                        for r
                        in valid
                    )
                    / len(
                        valid
                    )
                    if valid
                    else None
                ),
            "acceptable_accuracy":
                (
                    sum(
                        r[
                            "evaluation"
                        ][
                            "acceptable_correct"
                        ]
                        for r
                        in valid
                    )
                    / len(
                        valid
                    )
                    if valid
                    else None
                ),
            "mean_memory_characters":
                (
                    sum(
                        memory_sizes
                    )
                    / len(
                        memory_sizes
                    )
                    if memory_sizes
                    else 0
                ),
        }

    for mode, summary in summaries.items():
        initial_rows = [r for r in results if r["memory_mode"] == mode
                        and r["initial_routing_evaluation"]["strict_correct"] is not None]
        summary["initial_evaluated_routing_runs"] = len(initial_rows)
        for metric in ("strict", "acceptable"):
            summary["initial_" + metric + "_accuracy"] = (
                sum(r["initial_routing_evaluation"][metric + "_correct"] for r in initial_rows) / len(initial_rows)
                if initial_rows else None)
    return {
        "summary":
            summaries,
        "results":
            results,
        "memory_accuracy_metrics":
            (
                "not_computed_no_relevance_gold"
            ),
    }


def main():
    parser = argparse.ArgumentParser(
        description=__doc__
    )
    parser.add_argument("--primary-router", choices=("rule_similarity", "llm", "memory_aware_llm"),
                        default="rule_similarity", help="Encounter primary specialty router")

    parser.add_argument(
        "--source",
        type=Path,
        default=Path(
            "current_symptom_presentation_benchmark_v2.jsonl"
        ),
    )

    parser.add_argument(
        "--registry",
        type=Path,
        default=Path(
            "app/data/synthea_v2/registry_shared_qwen.json"
        ),
    )

    parser.add_argument(
        "--routing-case-ids",
        type=Path,
        help=(
            "JSON list of 10 recommended "
            "Routing case IDs"
        ),
    )

    parser.add_argument(
        "--candidate-report",
        type=Path,
        default=Path(
            "final_task_candidate_report_v2.md"
        ),
        help=(
            "Ranked Routing/Memory recommendations; "
            "used when present"
        ),
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "outputs/synthea_v2"
        ),
    )

    parser.add_argument(
        "--context-chars",
        type=int,
        default=60000,
        help=(
            "Maximum total request size in characters "
            "for system prompt + payload + output schema. "
            "This is a safety guard, not an exact tokenizer "
            "context-window measurement."
        ),
    )

    parser.add_argument(
        "--memory-chars",
        type=int,
        default=30000,
        help=(
            "Maximum serialized memory-record characters "
            "for Budgeted Full History and Selective Memory. "
            "Both memory conditions use the same budget."
        ),
    )

    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
    )

    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "Actual specialty calls; "
            "default stops before calls"
        ),
    )

    parser.add_argument("--max-model-calls", type=int, default=16, help="Total request ceiling per case/mode, including repairs")
    parser.add_argument("--max-router-calls", type=int, default=8, help="Router request ceiling, including repairs")
    parser.add_argument("--max-clinical-calls", type=int, default=8, help="Clinical request ceiling, including repairs")
    args = parser.parse_args()
    if min(args.max_model_calls, args.max_router_calls, args.max_clinical_calls) < 1:
        parser.error("Model call budgets must be positive")

    if (
        args.context_chars < 1
        or args.memory_chars < 2
        or args.top_k < 1
    ):
        parser.error(
            "Budgets must be positive"
        )

    if (
        args.memory_chars
        >= args.context_chars
    ):
        parser.error(
            "--memory-chars must be smaller "
            "than --context-chars so that current "
            "state, routing context and schema "
            "also fit in the request"
        )

    if args.output_dir.exists():
        parser.error(
            "Choose a new output directory; "
            "existing results are preserved"
        )

    fingerprint = digest(
        args.source
    )

    sources = [
        json.loads(
            line
        )
        for line
        in args.source.read_text(
            encoding="utf-8-sig"
        ).splitlines()
        if line.strip()
    ]

    by_id = {
        row[
            "case_id"
        ]: row
        for row in sources
    }

    assert (
        len(
            by_id
        )
        == len(
            sources
        )
    )

    manifest = json.loads(
        args.registry.read_text(
            encoding="utf-8-sig"
        )
    )

    AgentRegistry(
        manifest
    )

    routing = [
        row
        for row in sources
        if row[
            "final_task_eligibility"
        ][
            "routing_final_candidate"
        ]
    ]

    recommendations = (
        recommended_ids(
            args.candidate_report
        )
        if args.candidate_report.is_file()
        else None
    )

    if recommendations:
        for (
            task,
            ids,
        ) in recommendations.items():
            if any(
                (
                    case_id
                    not in by_id
                    or not by_id[
                        case_id
                    ][
                        "final_task_eligibility"
                    ][
                        task
                        + "_final_candidate"
                    ]
                )
                for case_id
                in ids
            ):
                raise ValueError(
                    f"Ineligible or missing "
                    f"{task} recommendation"
                )

    if args.routing_case_ids:
        ids = json.loads(
            args.routing_case_ids.read_text(
                encoding="utf-8-sig"
            )
        )

        assert (
            len(
                ids
            )
            == len(
                set(
                    ids
                )
            )
            == 10
        )

        routing_ids = {
            r[
                "case_id"
            ]
            for r in routing
        }

        assert all(
            case_id
            in routing_ids
            for case_id
            in ids
        )

        routing = [
            by_id[
                case_id
            ]
            for case_id
            in ids
        ]

        selection = (
            "provided_recommendation_ids"
        )

    elif recommendations:
        routing = [
            by_id[
                case_id
            ]
            for case_id
            in recommendations[
                "routing"
            ]
        ]

        selection = (
            "ranked_candidate_report"
        )

    else:
        chosen = [
            next(
                r
                for r
                in routing
                if r[
                    "evaluation"
                ][
                    "primary_specialty"
                ]
                == department
            )
            for department
            in (
                "otolaryngology",
                "surgery",
                "gastroenterology",
            )
        ]

        routing = (
            chosen
            + [
                r
                for r
                in routing
                if r
                not in chosen
            ]
        )[:10]

        selection = (
            "provisional_one_per_specialty_"
            "then_source_order; "
            "recommendation_list_not_found"
        )

    memory = [
        row
        for row in sources
        if row[
            "final_task_eligibility"
        ][
            "memory_final_candidate"
        ]
    ]

    if recommendations:
        memory = [
            by_id[
                case_id
            ]
            for case_id
            in recommendations[
                "memory"
            ]
        ]

    converted = {}
    patient_traces = []

    for source in sources:
        case, trace = (
            convert_case(
                source
            )
        )

        converted[
            source[
                "case_id"
            ]
        ] = case

        patient_traces.append(
            {
                "case_id":
                    source[
                        "case_id"
                    ],
                "patient_input":
                    case[
                        "synthea_v2_patient_input"
                    ],
                **trace,
            }
        )

    args.output_dir.mkdir(
        parents=True
    )

    def save(
        name,
        value,
    ):
        (
            args.output_dir
            / name
        ).write_text(
            json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    cache = {}

    def batch(
        rows,
        modes,
    ):
        results = []

        for source in rows:
            for mode in modes:
                key = (
                    source[
                        "case_id"
                    ],
                    mode,
                )

                if key not in cache:
                    cache[
                        key
                    ] = run_case(
                        converted[
                            key[
                                0
                            ]
                        ],
                        mode,
                        manifest,
                        args,
                    )

                    result = cache[
                        key
                    ]

                    memory_info = result.get(
                        "memory_budget",
                        {},
                    )

                    print(
                        key[
                            0
                        ],
                        mode,
                        result[
                            "status"
                        ],
                        (
                            f"memory_chars="
                            f"{memory_info.get('records_json_chars')}"
                            if mode
                            != "no_memory"
                            else ""
                        ),
                        (
                            f"records="
                            f"{memory_info.get('selected_count')}"
                            if mode
                            != "no_memory"
                            else ""
                        ),
                        flush=True,
                    )

                results.append(
                    deepcopy(
                        cache[
                            key
                        ]
                    )
                )

        return evaluate(
            results,
            by_id,
        )

    r_modes = (
        "no_memory",
        "selective",
    )

    m_modes = (
        "no_memory",
        "full_history_budgeted",
        "selective",
    )

    r_smoke = batch(
        routing[
            :3
        ],
        r_modes,
    )

    m_smoke = batch(
        memory[
            :3
        ],
        m_modes,
    )

    save(
        "routing_smoke.json",
        r_smoke,
    )

    save(
        "memory_smoke.json",
        m_smoke,
    )

    smoke_ok = all(
        (
            result[
                "boundary_reached"
            ]
            and (
                (args.live and result["runner_status"] == "completed")
                or (not args.live and result[
                    "status"
                ]
                in {
                    "stopped_before_model_call",
                    "context_limit_exceeded",
                })
            )
        )
        for result
        in (
            r_smoke[
                "results"
            ]
            + m_smoke[
                "results"
            ]
        )
    )

    if smoke_ok:
        save(
            "routing_pilot_results.json",
            batch(
                routing,
                r_modes,
            ),
        )

        save(
            "memory_pilot_results.json",
            batch(
                memory,
                m_modes,
            ),
        )

    (
        args.output_dir
        / "patient_agent_trace.jsonl"
    ).write_text(
        "\n".join(
            json.dumps(
                trace,
                ensure_ascii=False,
            )
            for trace
            in patient_traces
        )
        + "\n",
        encoding="utf-8",
    )

    assert (
        digest(
            args.source
        )
        == fingerprint
    )

    save(
        "validation.json",
        {
            "source":
                str(
                    args.source
                ),
            "source_sha256":
                fingerprint,
            "source_unchanged":
                True,

            "registry":
                str(
                    args.registry
                ),
            "registry_sha256":
                digest(
                    args.registry
                ),
            "registry_snapshot":
                manifest,

            "source_cases":
                len(
                    sources
                ),

            "routing_eligible":
                sum(
                    row[
                        "final_task_eligibility"
                    ][
                        "routing_final_candidate"
                    ]
                    for row
                    in sources
                ),

            "primary_router": args.primary_router,
            "model_call_limits": {"total": args.max_model_calls, "router": args.max_router_calls,
                                  "clinical": args.max_clinical_calls},
            "contract_repair_policy": "at_most_one_for_routing_score_or_department_diagnosis; no_network_retries",
            "routing_pilot_selection":
                selection,

            "routing_ids":
                [
                    row[
                        "case_id"
                    ]
                    for row
                    in routing
                ],

            "candidate_report":
                (
                    str(
                        args.candidate_report
                    )
                    if recommendations
                    else None
                ),

            "candidate_report_sha256":
                (
                    digest(
                        args.candidate_report
                    )
                    if recommendations
                    else None
                ),

            "memory_pilot_selection":
                (
                    "ranked_candidate_report"
                    if recommendations
                    else "source_eligibility_order"
                ),

            "memory_ids":
                [
                    row[
                        "case_id"
                    ]
                    for row
                    in memory
                ],

            "patient_grounded_cases":
                len(
                    patient_traces
                ),

            "voi_final_candidates":
                sum(
                    row[
                        "final_task_eligibility"
                    ][
                        "voi_final_candidate"
                    ]
                    for row
                    in sources
                ),

            "outcome_models":
                sum(
                    row[
                        "final_task_eligibility"
                    ].get(
                        "outcome_model"
                    )
                    is not None
                    for row
                    in sources
                ),

            "technical_smoke_passed":
                smoke_ok,

            "unique_case_mode_executions":
                len(
                    cache
                ),

            "actual_llm_calls":
                sum(
                    result[
                        "actual_llm_calls"
                    ]
                    for result
                    in cache.values()
                ),

            "context_chars":
                args.context_chars,

            "memory_chars":
                args.memory_chars,

            "top_k":
                args.top_k,

            "memory_conditions": {
                "no_memory": {
                    "description":
                        "No historical records are provided."
                },
                "full_history_budgeted": {
                    "description":
                        (
                            "All eligible historical records form the "
                            "candidate pool. Relevance scores are not used. "
                            "Most recent records are admitted first until "
                            "the fixed memory-character budget is reached."
                        ),
                    "max_memory_chars":
                        args.memory_chars,
                },
                "selective": {
                    "description":
                        (
                            "Existing selective lexical retrieval is used "
                            "with the same fixed memory-character budget."
                        ),
                    "top_k":
                        args.top_k,
                    "max_memory_chars":
                        args.memory_chars,
                },
            },

            "limitations": [
                (
                    "Registry coverage is fixed before evaluation "
                    "and is not expanded using gold labels."
                ),
                (
                    "Offline mode verifies integration rather than "
                    "clinical/model accuracy."
                ),
                (
                    "Character budgets are engineering guards and "
                    "are not exact tokenizer context-window limits."
                ),
                (
                    "Budgeted Full History is not literal unbounded "
                    "Full History; it is a recency-based finite-context "
                    "baseline."
                ),
                (
                    "Date-only memory uses next-day availability "
                    "upper bound."
                ),
                (
                    "Official memory retrieval accuracy is not "
                    "computed until relevance gold annotations exist."
                ),
            ],
        },
    )


if __name__ == "__main__":
    main()
