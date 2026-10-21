
"""Build reproducible lexical vectors or real Ollama embedding artifacts."""

import hashlib
import json
import re
from urllib.request import Request, urlopen

from app.core.longitudinal_memory import (
    PatientMemoryStore,
    visit_identity,
)
from app.core.memory_evaluation import visit_key
from app.core.memory_retrieval import MemoryEmbeddings
from app.core.clinical_observation import memory_query
from app.core.memory_benchmark_query import (
    prepare_memory_case,
    build_initial_memory_query,
)


def lexical_vector(text, dimensions=256):
    vector = [0.0] * dimensions

    for token in re.findall(
        r"\w+", text.casefold()
    ) or ["<empty>"]:
        index = (
            int(
                hashlib.sha256(
                    token.encode()
                ).hexdigest(),
                16,
            )
            % dimensions
        )
        vector[index] += 1

    return vector


def build_embeddings(
    records,
    cases,
    *,
    model="lexical-hash-256",
    revision="v1",
    endpoint=None,
    batch_size=32,
    embed=None,
    cpu=False,
    query_states=(),
):
    """Generate versioned memory and query embeddings.

    The initial query construction is shared with the
    memory retrieval benchmark to prevent mismatched hashes.
    """
    PatientMemoryStore(records)

    if (
        type(batch_size) is not int
        or batch_size < 1
    ):
        raise ValueError(
            "batch_size must be positive"
        )

    queries = {}

    for source in cases:
        case = prepare_memory_case(source)

        identity = visit_identity(case)
        key = visit_key(identity)

        query = build_initial_memory_query(
            case,
            prepared=True,
        )

        if key in queries and queries[key] != query:
            raise ValueError(
                "Conflicting queries for the same visit"
            )

        queries[key] = query

    for state in query_states:
        query = memory_query(state)

        queries[
            MemoryEmbeddings.text_hash(query)
        ] = query

    texts = {
        "records": {
            record["memory_id"]: record["text"]
            for record in records
        },
        "queries": queries,
    }

    unique = list(
        dict.fromkeys(
            text
            for group in texts.values()
            for text in group.values()
        )
    )

    vectors = {}

    for offset in range(
        0,
        len(unique),
        batch_size,
    ):
        batch = unique[
            offset:offset + batch_size
        ]

        if embed is not None:
            values = embed(batch)

        elif model == "lexical-hash-256":
            if revision != "v1":
                raise ValueError(
                    "Unknown lexical vector version"
                )

            values = [
                lexical_vector(text)
                for text in batch
            ]

        else:
            if not endpoint:
                raise ValueError(
                    "A native Ollama base URL is "
                    "required for model embeddings"
                )

            body = {
                "model": model,
                "input": batch,
                "truncate": False,
            }

            if cpu:
                body["options"] = {
                    "num_gpu": 0
                }

            request = Request(
                endpoint.rstrip("/") + "/api/embed",
                data=json.dumps(body).encode(),
                headers={
                    "Content-Type": "application/json"
                },
            )

            with urlopen(
                request,
                timeout=120,
            ) as response:
                values = json.load(
                    response
                )["embeddings"]

        if len(values) != len(batch):
            raise ValueError(
                "Embedding response count mismatch"
            )

        vectors.update(
            zip(batch, values)
        )

    artifact = {
        "model_id": model,
        "revision": revision,
    }

    for name, group in texts.items():
        artifact[name] = {
            key: {
                "text_sha256": (
                    MemoryEmbeddings.text_hash(text)
                ),
                "vector": vectors[text],
            }
            for key, text in group.items()
        }

    MemoryEmbeddings(artifact)

    return artifact
