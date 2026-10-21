from copy import deepcopy
import json
import unittest

from test_longitudinal_memory import record, IDENTITY
from test_diagnostic_gate import Client, response, source

from app.core.longitudinal_memory import PatientMemoryStore
from app.core.longitudinal_runner import run_longitudinal
from app.core.memory_evaluation import (
    evaluate_memory,
    compare_memory_benefit,
    visit_key,
)
from app.core.memory_retrieval import MemoryEmbeddings
from app.core.hospital_parallel_scheduler import HospitalParallelScheduler
from app.core.hospital_llm_policy import HospitalLLMPolicy


def case():
    result = source()
    result["longitudinal"] = deepcopy(IDENTITY)
    return result


def replies():
    return [
        response(
            "request_test",
            target="T",
        ),
        response(
            certainty="supported",
            indices=[0],
        ),
    ]


class MemoryResearchTests(unittest.TestCase):

    def test_precision_recall_stale_and_missing_annotations(self):
        context = {
            "records": [
                {"memory_id": "a"},
                {"memory_id": "b"},
            ]
        }

        score = evaluate_memory(
            context,
            [],
            {
                "relevant_memory_ids": [
                    "a",
                    "c",
                ],
                "stale_memory_ids": [
                    "b",
                ],
            },
        )

        self.assertEqual(
            score["precision"]["value"],
            0.5,
        )

        self.assertEqual(
            score["recall"]["value"],
            0.5,
        )

        self.assertEqual(
            score["stale_retrieval_rate"]["value"],
            0.5,
        )

        self.assertIsNone(
            score[
                "stale_misuse_rate"
            ]["value"]
        )

        self.assertIsNone(
            evaluate_memory(
                context,
                [],
            )[
                "precision"
            ]["value"]
        )

        self.assertEqual(
            evaluate_memory(
                {},
                [],
                {
                    "relevant_memory_ids": [],
                },
            )[
                "recall"
            ]["status"],
            "not_applicable",
        )

    def test_misuse_requires_explicit_review_not_just_citation(self):
        context = {
            "records": [
                {
                    "memory_id": "a",
                }
            ]
        }

        audit = [
            {
                "role": "er",
                "status": "success",
                "memory_citations": {
                    "ids": [
                        "a",
                    ],
                    "reported": True,
                },
            }
        ]

        score = evaluate_memory(
            context,
            audit,
            {
                "stale_memory_ids": [
                    "a",
                ],
                "misused_memory_ids": [],
            },
        )

        self.assertEqual(
            score[
                "stale_misuse_rate"
            ]["value"],
            0,
        )

        self.assertEqual(
            score["cited_ids"],
            [
                "a",
            ],
        )

        with self.assertRaises(
            ValueError
        ):
            evaluate_memory(
                context,
                audit,
                {
                    "relevant_memory_ids": [
                        "future",
                    ],
                },
                eligible_ids=[
                    "a",
                ],
            )

    def test_fixed_memory_does_not_ingest_predictions_or_leak_labels(self):
        client = Client(
            *replies()
        )

        labels = {
            visit_key(
                IDENTITY
            ): {
                "relevant_memory_ids": [
                    "old",
                ],
                "stale_memory_ids": [],
            }
        }

        result = run_longitudinal(
            [
                case(),
            ],
            mode="full_history",
            initial_memory=[
                record(),
            ],
            memory_source="fixed",
            memory_annotations=labels,
            client=client,
        )

        self.assertEqual(
            len(
                result[
                    "memory"
                ][
                    "records"
                ]
            ),
            1,
        )

        self.assertEqual(
            result[
                "visits"
            ][0][
                "memory_evaluation"
            ][
                "recall"
            ][
                "value"
            ],
            1,
        )

        self.assertNotIn(
            "relevant_memory_ids",
            json.dumps(
                client.payloads
            ),
        )

    def test_updates_are_committed_and_available_next_visit(self):
        first = case()

        first[
            "longitudinal"
        ][
            "memory_updates"
        ] = [
            record(
                "new",
                visit="v2",
                date=IDENTITY[
                    "started_at"
                ],
                kind="update",
                text=(
                    "synthetic changed"
                ),
                supersedes=[
                    "old",
                ],
            )
        ]

        second = deepcopy(
            first
        )

        second[
            "case_id"
        ] = "second"

        second[
            "longitudinal"
        ] = {
            **IDENTITY,
            "visit_id": "v3",
            "started_at": (
                "2026-03-01T00:00:00Z"
            ),
        }

        result = run_longitudinal(
            [
                first,
                second,
            ],
            mode="selective",
            initial_memory=[
                record(),
            ],
            client=Client(
                *replies(),
                *replies(),
            ),
        )

        ids = [
            r[
                "memory_id"
            ]
            for r in result[
                "visits"
            ][1][
                "memory_context"
            ][
                "records"
            ]
        ]

        self.assertIn(
            "new",
            ids,
        )

        self.assertNotIn(
            "old",
            ids,
        )

    def test_fixed_mode_rejects_visit_dependent_updates(self):
        data = case()

        data[
            "longitudinal"
        ][
            "memory_updates"
        ] = [
            record(),
        ]

        client = Client()

        with self.assertRaises(
            ValueError
        ):
            run_longitudinal(
                [
                    data,
                ],
                memory_source="fixed",
                initial_memory=[],
                client=client,
            )

        self.assertEqual(
            client.payloads,
            [],
        )

    def test_summary_is_extractive_and_budgeted(self):
        store = PatientMemoryStore(
            [
                record(),
                record(
                    "new",
                    date=(
                        "2026-01-02T00:00:00Z"
                    ),
                    text=(
                        "new synthetic observation"
                    ),
                ),
                record(
                    "history",
                    kind="history",
                    text=(
                        "source history"
                    ),
                ),
            ]
        )

        rows = store.retrieve(
            IDENTITY,
            "",
            "summary",
        )[
            "records"
        ]

        self.assertEqual(
            {
                r[
                    "memory_id"
                ]
                for r in rows
            },
            {
                "new",
                "history",
            },
        )

        original = {
            r[
                "memory_id"
            ]: r[
                "text"
            ]
            for r in store.snapshot()[
                "records"
            ]
        }

        self.assertTrue(
            all(
                r[
                    "text"
                ]
                == original[
                    r[
                        "memory_id"
                    ]
                ]
                for r in rows
            )
        )

        bounded = store.retrieve(
            IDENTITY,
            "",
            "full_history",
            max_chars=2,
        )

        self.assertEqual(
            bounded[
                "records"
            ],
            [],
        )

        self.assertEqual(
            bounded[
                "records_json_chars"
            ],
            2,
        )

        self.assertEqual(
            bounded[
                "budget_excluded_count"
            ],
            3,
        )

    def artifact(self):
        def item(
            text,
            vector,
        ):
            return {
                "text_sha256": (
                    MemoryEmbeddings
                    .text_hash(
                        text
                    )
                ),
                "vector": vector,
            }

        return {
            "model_id": (
                "synthetic-vectors"
            ),
            "revision": (
                "test-v1"
            ),
            "records": {
                "old": item(
                    "synthetic finding",
                    [
                        1,
                        0,
                    ],
                ),
                "other": item(
                    "unrelated text",
                    [
                        0,
                        1,
                    ],
                ),
            },
            "queries": {
                visit_key(
                    IDENTITY
                ): item(
                    "different words",
                    [
                        1,
                        0,
                    ],
                )
            },
        }

    def test_vector_similarity_and_temporal_filter_before_scoring(self):
        store = PatientMemoryStore(
            [
                record(),
                record(
                    "other",
                    text=(
                        "unrelated text"
                    ),
                ),
                record(
                    "future",
                    date=(
                        "2026-03-01T00:00:00Z"
                    ),
                ),
            ]
        )

        rows = store.retrieve(
            IDENTITY,
            "different words",
            "semantic",
            embeddings=MemoryEmbeddings(
                self.artifact()
            ),
        )[
            "records"
        ]

        self.assertEqual(
            [
                r[
                    "memory_id"
                ]
                for r in rows
            ],
            [
                "old",
            ],
        )

        self.assertEqual(
            rows[0][
                "retrieval_score"
            ],
            1,
        )

        # Future item has no vector.
        # Temporal filtering must happen
        # before embedding lookup.

    def test_embedding_mismatch_and_nonfinite_rejected(self):
        artifact = self.artifact()

        artifact[
            "queries"
        ][
            visit_key(
                IDENTITY
            )
        ][
            "vector"
        ] = [
            float(
                "nan"
            ),
            0,
        ]

        with self.assertRaises(
            ValueError
        ):
            MemoryEmbeddings(
                artifact
            )

        with self.assertRaises(
            ValueError
        ):
            PatientMemoryStore(
                [
                    record(),
                ]
            ).retrieve(
                IDENTITY,
                "changed query",
                "semantic",
                embeddings=MemoryEmbeddings(
                    self.artifact()
                ),
            )

    def test_actual_observation_times_preserved(self):
        runtime = (
            HospitalParallelScheduler()
            .initialize(
                [
                    case(),
                ]
            )
            .case(
                "gate"
            )
        )

        runtime.is_completed = True
        runtime.final_diagnosis_min = 10

        runtime.question_history = [
            {
                "answer": (
                    "known observation"
                ),
                "observed_minute": 2,
            }
        ]

        runtime.objective_findings = [
            "T: finding",
        ]

        runtime.test_results = [
            {
                "test_name": "T",
                "observed_minute": 4,
            }
        ]

        store = PatientMemoryStore()

        store.ingest_completed_visit(
            runtime
        )

        rows = store.snapshot()[
            "records"
        ]

        self.assertTrue(
            rows[0][
                "observed_at"
            ].endswith(
                "00:02:00+00:00"
            )
        )

        self.assertTrue(
            rows[1][
                "observed_at"
            ].endswith(
                "00:04:00+00:00"
            )
        )

    def test_invalid_memory_citation_is_filtered_and_recorded(self):
        """
        Invalid citation IDs are a memory-reliability
        issue, not a fatal clinical episode error.

        Valid IDs remain.
        Invalid IDs are removed and recorded
        in the audit.
        """

        for key in (
            "old",
            "other-patient",
        ):
            runtime = (
                HospitalParallelScheduler()
                .initialize(
                    [
                        case(),
                    ]
                )
                .case(
                    "gate"
                )
            )

            runtime.memory_context = (
                PatientMemoryStore(
                    [
                        record(),
                    ]
                )
                .retrieve(
                    IDENTITY,
                    "synthetic",
                )
            )

            row = json.loads(
                response(
                    "request_test",
                    target="T",
                )
            )

            row[
                "memory_ids"
            ] = [
                key,
            ]

            policy = HospitalLLMPolicy(
                {
                    "max_decisions": 12,
                    "max_questions": 2,
                },
                client=Client(
                    json.dumps(
                        row
                    )
                ),
            )

            policy.evaluate_er_case(
                runtime,
                doctor_id="er",
            )

            citation = (
                runtime
                .llm_audit[-1]
                [
                    "memory_citations"
                ]
            )

            if key == "old":
                self.assertEqual(
                    citation[
                        "ids"
                    ],
                    [
                        "old",
                    ],
                )

                self.assertEqual(
                    citation[
                        "invalid_ids"
                    ],
                    [],
                )

                self.assertTrue(
                    citation[
                        "valid"
                    ]
                )

            else:
                self.assertEqual(
                    citation[
                        "ids"
                    ],
                    [],
                )

                self.assertEqual(
                    citation[
                        "invalid_ids"
                    ],
                    [
                        "other-patient",
                    ],
                )

                self.assertFalse(
                    citation[
                        "valid"
                    ]
                )

    def test_ask_patient_without_question_mark_is_normalized(self):
        """
        A missing terminal question mark is a
        formatting issue.

        It should be normalized instead of
        causing the entire episode to fail.
        """

        runtime = (
            HospitalParallelScheduler()
            .initialize(
                [
                    case(),
                ]
            )
            .case(
                "gate"
            )
        )

        row = json.loads(
            response(
                "ask_patient",
                target=(
                    "When did symptoms start"
                ),
            )
        )

        # First response:
        # physician decision.
        #
        # Second response:
        # PatientAgent fact-selection response.
        client = Client(
            json.dumps(
                row
            ),
            json.dumps(
                {
                    "fact_ids": [],
                    "unknown": True,
                }
            ),
        )

        policy = HospitalLLMPolicy(
            {
                "max_decisions": 12,
                "max_questions": 2,
            },
            client=client,
        )

        result = (
            policy
            .evaluate_er_case(
                runtime,
                doctor_id="er",
            )
        )

        self.assertEqual(
            result[
                "target"
            ],
            "When did symptoms start?",
        )

        # The physician call is the first
        # audit entry. The PatientAgent call
        # becomes another entry afterwards.
        physician_audit = (
            runtime
            .llm_audit[0]
        )

        self.assertTrue(
            physician_audit[
                "output_normalization"
            ][
                "question_punctuation_fixed"
            ]
        )

    def test_failed_run_is_reported_without_committing_visit(self):
        result = run_longitudinal(
            [
                case(),
            ],
            client=Client(
                "invalid json"
            ),
        )

        self.assertEqual(
            result[
                "status"
            ],
            "failed",
        )

        self.assertEqual(
            result[
                "memory"
            ][
                "records"
            ],
            [],
        )

        self.assertEqual(
            len(
                result[
                    "visits"
                ]
            ),
            1,
        )

    def test_paired_benefit_rejects_mismatched_contracts_and_preserves_missing(self):
        left = run_longitudinal(
            [
                case(),
            ],
            mode="none",
            memory_source="fixed",
            initial_memory=[
                record(),
            ],
            client=Client(
                *replies()
            ),
        )

        right = run_longitudinal(
            [
                case(),
            ],
            mode="summary",
            memory_source="fixed",
            initial_memory=[
                record(),
            ],
            client=Client(
                *replies()
            ),
        )

        score = compare_memory_benefit(
            left,
            right,
            {
                visit_key(
                    IDENTITY
                ): [
                    "synthetic diagnosis",
                ]
            },
        )

        self.assertEqual(
            score[
                "memory_benefit"
            ],
            0,
        )

        self.assertIsNone(
            compare_memory_benefit(
                left,
                right,
                {},
            )[
                "memory_benefit"
            ]
        )

        right[
            "experiment_signature"
        ] = "different"

        with self.assertRaises(
            ValueError
        ):
            compare_memory_benefit(
                left,
                right,
                {},
            )

    def test_posthoc_evaluation_keeps_labels_outside_run(self):
        from app.scripts.evaluate_longitudinal_memory import (
            evaluate_report,
        )

        report = run_longitudinal(
            [
                case(),
            ],
            mode="summary",
            memory_source="fixed",
            initial_memory=[
                record(),
            ],
            client=Client(
                *replies()
            ),
        )

        result = evaluate_report(
            report,
            {
                visit_key(
                    IDENTITY
                ): {
                    "relevant_memory_ids": [
                        "old",
                    ]
                }
            },
        )

        self.assertEqual(
            result[
                "visits"
            ][0][
                "metrics"
            ][
                "recall"
            ][
                "value"
            ],
            1,
        )

        with self.assertRaises(
            ValueError
        ):
            evaluate_report(
                report,
                {
                    visit_key(
                        IDENTITY
                    ): {
                        "relevant_memory_ids": [
                            "future",
                        ]
                    }
                },
            )

    def test_malformed_embedding_entry_rejected(self):
        artifact = self.artifact()

        artifact[
            "records"
        ][
            "old"
        ] = {}

        with self.assertRaises(
            ValueError
        ):
            MemoryEmbeddings(
                artifact
            )


if __name__ == "__main__":
    unittest.main()