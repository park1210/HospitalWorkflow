
import pytest

from app.core.memory_ranking_metrics import (
    evaluate_ranking,
)


def test_perfect_retrieval():
    result = evaluate_ranking(
        ["m1", "m2", "m3"],
        ["m1", "m2"],
        k=3,
    )

    assert result["recall_at_k"] == 1.0
    assert result["reciprocal_rank"] == 1.0
    assert result["precision_at_k"] == pytest.approx(2 / 3)


def test_relevant_record_at_third():
    result = evaluate_ranking(
        ["m1", "m2", "m3"],
        ["m3"],
        k=3,
    )

    assert result["reciprocal_rank"] == pytest.approx(1 / 3)
    assert result["hit_at_k"] == 1


def test_no_relevant_record_found():
    result = evaluate_ranking(
        ["m1", "m2"],
        ["m3"],
        k=2,
    )

    assert result["recall_at_k"] == 0.0
    assert result["reciprocal_rank"] == 0.0


def test_duplicate_retrieval_rejected():
    with pytest.raises(ValueError):
        evaluate_ranking(
            ["m1", "m1"],
            ["m1"],
            k=2,
        )
