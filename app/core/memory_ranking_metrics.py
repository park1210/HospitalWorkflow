
"""Rank-based memory retrieval metrics."""


def evaluate_ranking(
    retrieved_ids,
    relevant_ids,
    *,
    k,
):
    if type(k) is not int or k < 1:
        raise ValueError("k must be a positive integer")

    retrieved_ids = list(retrieved_ids)
    relevant = set(relevant_ids)

    if len(retrieved_ids) != len(set(retrieved_ids)):
        raise ValueError("Duplicate retrieved memory IDs")

    selected = retrieved_ids[:k]

    hits = sum(
        memory_id in relevant
        for memory_id in selected
    )

    first_rank = next(
        (
            index
            for index, memory_id in enumerate(
                selected, start=1
            )
            if memory_id in relevant
        ),
        None,
    )

    return {
        "precision_at_k": hits / k,
        "recall_at_k": (
            hits / len(relevant)
            if relevant else None
        ),
        "reciprocal_rank": (
            1 / first_rank
            if first_rank is not None
            else 0.0
        ),
        "hit_at_k": int(hits > 0),
        "retrieved_count": len(selected),
        "relevant_count": len(relevant),
        "first_relevant_rank": first_rank,
    }
