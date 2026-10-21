
"""Compare memory retrieval strategies using saved embeddings.

No new embedding or LLM calls are performed.
Gold annotations are used only for evaluation.
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path

from app.core.longitudinal_memory import (
    PatientMemoryStore,
    visit_identity,
    timestamp,
)
from app.core.memory_evaluation import (
    evaluate_memory,
    visit_key,
    validate_annotations,
)
from app.core.memory_retrieval import MemoryEmbeddings
from app.core.memory_benchmark_query import (
    prepare_memory_case,
    build_initial_memory_query,
)
from app.core.memory_ranking_metrics import (
    evaluate_ranking,
)


def average(values):
    valid = [
        value for value in values
        if value is not None
    ]
    return (
        sum(valid) / len(valid)
        if valid else None
    )


def compare(
    cases,
    memory,
    annotations,
    *,
    embeddings=None,
    top_ks=(1, 3),
    groups=None,
):
    """Evaluate multiple retrieval strategies on identical cases."""
    if (
        not cases
        or not top_ks
        or any(
            type(k) is not int or k < 1
            for k in top_ks
        )
    ):
        raise ValueError(
            "Need nonempty cases and positive top-k values"
        )

    if memory.get("schema_version") != 1:
        raise ValueError(
            "Unsupported memory schema"
        )

    validate_annotations(annotations)

    prepared_cases = [
        prepare_memory_case(case)
        for case in cases
    ]

    identities = [
        visit_identity(case)
        for case in prepared_cases
    ]

    keys = [
        visit_key(identity)
        for identity in identities
    ]

    if (
        len(keys) != len(set(keys))
        or set(keys) != set(annotations)
    ):
        raise ValueError(
            "Unique visits and exact annotation coverage required"
        )

    store = PatientMemoryStore(
        memory["records"]
    )

    vectors = (
        MemoryEmbeddings(embeddings)
        if embeddings is not None
        else None
    )

    vector_name = None

    if vectors:
        vector_name = (
            "lexical_hash_vectors"
            if vectors.payload["model_id"]
            == "lexical-hash-256"
            else "saved_model_vectors"
        )

    settings = [
        ("none", "none", 1),
        ("full_history", "full_history", None),
    ]

    for k in sorted(set(top_ks)):
        settings.append(
            ("lexical", "selective", k)
        )

        if vectors:
            settings.append(
                (vector_name, "semantic", k)
            )

    rows = []

    for case, identity, key in zip(
        prepared_cases,
        identities,
        keys,
    ):
        query = build_initial_memory_query(
            case,
            prepared=True,
        )

        eligible_context = store.retrieve(
            identity,
            query,
            mode="full_history",
        )

        eligible_ids = [
            row["memory_id"]
            for row in eligible_context["records"]
        ]

        eligible_set = set(eligible_ids)

        annotation = annotations[key]

        if "relevant_memory_ids" not in annotation:
            raise ValueError(
                f"Missing gold relevance for visit: {key}"
            )

        relevant_ids = annotation[
            "relevant_memory_ids"
        ]

        if len(relevant_ids) != len(
            set(relevant_ids)
        ):
            raise ValueError(
                f"Duplicate gold IDs: {key}"
            )

        if not set(relevant_ids) <= eligible_set:
            raise ValueError(
                f"Gold references unavailable records: {key}"
            )

        for method, mode, k in settings:
            # Full history is intentionally not a Top-K
            # method; evaluate its full returned context.
            retrieval_k = k if k is not None else 1

            context = store.retrieve(
                identity,
                query,
                mode=mode,
                top_k=retrieval_k,
                embeddings=vectors,
            )

            for record in context["records"]:
                if (
                    record["patient_id"]
                    != identity["patient_id"]
                    or record["visit_id"]
                    == identity["visit_id"]
                    or timestamp(
                        record["visit_started_at"]
                    ) >= timestamp(
                        identity["started_at"]
                    )
                    or timestamp(
                        record["available_at"]
                    ) > timestamp(
                        identity["started_at"]
                    )
                ):
                    raise ValueError(
                        "Retrieval crossed patient/visit/time boundary"
                    )

            metrics = evaluate_memory(
                context,
                [],
                annotation,
                eligible_ids,
            )

            ranked_ids = [
                record["memory_id"]
                for record in context["records"]
            ]

            # The full-history baseline is measured over
            # its entire returned context, not at a fake K=1.
            evaluation_k = (
                k if k is not None
                else max(len(ranked_ids), 1)
            )

            ranking = evaluate_ranking(
                ranked_ids,
                relevant_ids,
                k=evaluation_k,
            )

            rows.append({
                "visit": key,
                "group": (
                    groups or {}
                ).get(key, "unspecified"),
                "method": method,
                "top_k": k,
                "evaluation_k": evaluation_k,
                "eligible_count": len(eligible_ids),
                "retrieved_count": len(ranked_ids),
                "precision": (
                    metrics["precision"]["value"]
                ),
                "recall": (
                    metrics["recall"]["value"]
                ),
                "stale_rate": (
                    metrics[
                        "stale_retrieval_rate"
                    ]["value"]
                ),
                "precision_at_k": (
                    ranking["precision_at_k"]
                ),
                "recall_at_k": (
                    ranking["recall_at_k"]
                ),
                "reciprocal_rank": (
                    ranking["reciprocal_rank"]
                ),
                "hit_at_k": (
                    ranking["hit_at_k"]
                ),
                "retrieved_ids": ranked_ids,
                "relevant_ids": relevant_ids,
                "conflict_candidates": len(
                    context.get("conflicts", [])
                ),
            })

    summary = []

    metrics_to_aggregate = (
        "precision",
        "recall",
        "stale_rate",
        "precision_at_k",
        "recall_at_k",
        "reciprocal_rank",
        "hit_at_k",
    )

    group_names = [
        "ALL",
        *sorted({
            row["group"]
            for row in rows
            if row["group"] != "ALL"
        }),
    ]

    for group in group_names:
        for method, _, k in settings:
            subset = [
                row
                for row in rows
                if (
                    row["method"] == method
                    and row["top_k"] == k
                    and (
                        group == "ALL"
                        or row["group"] == group
                    )
                )
            ]

            result = {
                "group": group,
                "method": method,
                "top_k": k,
                "visits": len(subset),
            }

            for metric in metrics_to_aggregate:
                values = [
                    row[metric]
                    for row in subset
                ]

                valid_count = sum(
                    value is not None
                    for value in values
                )

                result[metric] = average(values)

                result[
                    metric + "_coverage"
                ] = (
                    valid_count / len(subset)
                    if subset else None
                )

            # MRR is the macro-average reciprocal rank.
            result["mrr"] = result[
                "reciprocal_rank"
            ]

            summary.append(result)

    return {
        "new_model_calls": 0,
        "summary": summary,
        "rows": rows,
        "embedding_model": (
            vectors.payload["model_id"]
            if vectors else None
        ),
        "embedding_revision": (
            vectors.payload["revision"]
            if vectors else None
        ),
        "embedding_sha256": (
            vectors.fingerprint
            if vectors else None
        ),
        "interpretation": (
            "Saved embeddings are supplied artifacts. "
            "Retrieval relevance depends on supplied gold "
            "annotations. Full history is reported separately "
            "from fixed Top-K strategies. Semantic retrieval "
            "retains the existing positive-cosine filter. "
            "Scores do not establish clinical validity."
        ),
    }


def main():
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    for name in (
        "cases",
        "memory",
        "annotations",
    ):
        parser.add_argument(
            "--" + name,
            type=Path,
            required=True,
        )

    parser.add_argument(
        "--embeddings",
        type=Path,
    )
    parser.add_argument(
        "--scenarios",
        type=Path,
    )
    parser.add_argument(
        "--top-k",
        type=int,
        nargs="+",
        default=[1, 3, 5],
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--paper-plan",
        type=Path,
        help=(
            "Also prepare a semantic B0-B4 experiment "
            "plan using matching inputs"
        ),
    )

    args = parser.parse_args()

    def read(path):
        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    scenarios = (
        read(args.scenarios)
        if args.scenarios
        else []
    )

    groups = {
        visit_key(row): row["group"]
        for row in scenarios
    }

    if len(groups) != len(scenarios):
        raise ValueError(
            "Duplicate scenario IDs"
        )

    result = compare(
        read(args.cases),
        read(args.memory),
        read(args.annotations),
        embeddings=(
            read(args.embeddings)
            if args.embeddings
            else None
        ),
        top_ks=args.top_k,
        groups=groups,
    )

    semantic_plan = None

    if args.paper_plan:
        if (
            not args.embeddings
            or result["embedding_model"]
            == "lexical-hash-256"
        ):
            raise ValueError(
                "Semantic experiment plan requires "
                "non-lexical model vectors"
            )

        from app.scripts.run_paper_experiments import (
            prepare,
        )

        semantic_plan, _, _ = prepare(
            args.paper_plan.resolve()
        )

        for name in (
            "cases",
            "memory",
            "annotations",
        ):
            source = (
                args.paper_plan.resolve().parent
                / semantic_plan["inputs"][name]
            )

            if (
                hashlib.sha256(
                    source.read_bytes()
                ).digest()
                != hashlib.sha256(
                    getattr(args, name).read_bytes()
                ).digest()
            ):
                raise ValueError(
                    "Comparison data differs from paper plan: "
                    + name
                )

        semantic_plan["inputs"] = {
            key: str(
                (
                    args.paper_plan.resolve().parent
                    / value
                ).resolve()
            )
            for key, value
            in semantic_plan["inputs"].items()
        }

        semantic_plan["inputs"]["embeddings"] = str(
            args.embeddings.resolve()
        )

        semantic_plan["retrieved_mode"] = "semantic"

    result["input_sha256"] = {
        name: hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for name in (
            "cases",
            "memory",
            "annotations",
            "embeddings",
            "scenarios",
        )
        if (
            path := getattr(args, name)
        ) is not None
    }

    args.output_dir.mkdir(
        parents=True,
        exist_ok=False,
    )

    if semantic_plan is not None:
        target = (
            args.output_dir / "plan_semantic.json"
        )

        target.write_text(
            json.dumps(
                semantic_plan,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        prepare(target.resolve())

    (
        args.output_dir / "comparison.json"
    ).write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )

    summary_path = (
        args.output_dir / "summary.csv"
    )

    with summary_path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=list(
                result["summary"][0]
            ),
        )

        writer.writeheader()
        writer.writerows(
            result["summary"]
        )

    lines = [
        "# Memory retrieval comparison",
        "",
        result["interpretation"],
        "",
        (
            f"Embedding model: "
            f"{result['embedding_model']}"
        ),
        (
            f"New model calls: "
            f"{result['new_model_calls']}"
        ),
        "",
        "| Group | Method | K | P@K | R@K | MRR | Hit@K |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]

    for row in result["summary"]:
        lines.append(
            "| "
            + " | ".join(
                str(value)
                for value in (
                    row["group"],
                    row["method"],
                    row["top_k"],
                    row["precision_at_k"],
                    row["recall_at_k"],
                    row["mrr"],
                    row["hit_at_k"],
                )
            )
            + " |"
        )

    (
        args.output_dir / "comparison.md"
    ).write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    print(
        "Memory retrieval comparison complete: "
        f"{args.output_dir}"
    )


if __name__ == "__main__":
    main()
