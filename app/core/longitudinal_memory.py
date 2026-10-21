"""Patient-scoped, time-bounded memory; no inference or gold-label ingestion."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re

from app.core.diagnostic_evidence import informative
from app.core.memory_conflicts import detect_conflicts


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError(
            "Memory timestamps must be ISO-8601 strings with a timezone"
        )

    result = datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )

    if result.utcoffset() is None:
        raise ValueError(
            "Memory timestamps require an explicit timezone"
        )

    return result.astimezone(timezone.utc)


def visit_identity(case):
    identity = case.get("longitudinal", {})

    for key in (
        "patient_id",
        "visit_id",
        "started_at",
    ):
        if (
            not isinstance(identity.get(key), str)
            or not identity[key].strip()
        ):
            raise ValueError(
                f"Missing longitudinal.{key}"
            )

    timestamp(identity["started_at"])

    return {
        key: identity[key]
        for key in (
            "patient_id",
            "visit_id",
            "started_at",
        )
    }


class PatientMemoryStore:

    def __init__(self, records=()):
        self._records = []

        for record in records:
            self.add(record)

    def add(self, record):
        required = {
            "memory_id",
            "patient_id",
            "visit_id",
            "visit_started_at",
            "observed_at",
            "available_at",
            "source_id",
            "kind",
            "text",
            "supersedes",
        }

        if set(record) != required:
            raise ValueError(
                "Memory record fields must match the explicit schema"
            )

        if any(
            not isinstance(record[k], str)
            or not record[k].strip()
            for k in required - {"supersedes"}
        ):
            raise ValueError(
                "Memory fields must be nonempty strings"
            )

        if record["kind"] not in {
            "history",
            "objective_finding",
            "prior_assessment",
            "intervention",
            "update",
        }:
            raise ValueError(
                "Unsupported memory kind"
            )

        start, observed, available = (
            timestamp(record[k])
            for k in (
                "visit_started_at",
                "observed_at",
                "available_at",
            )
        )

        if not start <= observed <= available:
            raise ValueError(
                "Memory chronology must satisfy "
                "visit <= observation <= availability"
            )

        if any(
            r["memory_id"] == record["memory_id"]
            for r in self._records
        ):
            raise ValueError(
                "Duplicate memory_id"
            )

        if (
            not isinstance(record["supersedes"], list)
            or any(
                not isinstance(x, str)
                for x in record["supersedes"]
            )
        ):
            raise ValueError(
                "supersedes must be a list of memory IDs"
            )

        for memory_id in record["supersedes"]:
            old = next(
                (
                    r
                    for r in self._records
                    if r["memory_id"] == memory_id
                ),
                None,
            )

            if (
                old is None
                or old["patient_id"]
                != record["patient_id"]
                or timestamp(old["available_at"])
                > available
            ):
                raise ValueError(
                    "Updates require an earlier available "
                    "record of the same patient"
                )

        self._records.append(
            deepcopy(record)
        )

    def snapshot(self):
        return {
            "schema_version": 1,
            "records": deepcopy(
                self._records
            ),
        }

    def save(self, path):
        path = Path(path)

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            json.dumps(
                self.snapshot(),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path):
        payload = json.loads(
            Path(path).read_text(
                encoding="utf-8"
            )
        )

        if payload.get(
            "schema_version"
        ) != 1:
            raise ValueError(
                "Unsupported memory schema version"
            )

        return cls(
            payload["records"]
        )

    def retrieve(
        self,
        identity,
        query,
        mode="selective",
        top_k=5,
        *,
        max_chars=None,
        embeddings=None,
    ):
        if mode not in {
            "none",
            "full_history",
            "selective",
            "summary",
            "semantic",
        }:
            raise ValueError(
                "Unknown memory mode"
            )

        if (
            isinstance(top_k, bool)
            or not isinstance(top_k, int)
            or top_k < 1
        ):
            raise ValueError(
                "top_k must be positive"
            )

        if (
            max_chars is not None
            and (
                type(max_chars) is not int
                or max_chars < 2
            )
        ):
            raise ValueError(
                "max_chars must be an integer "
                "of at least 2"
            )

        cutoff = timestamp(
            identity["started_at"]
        )

        eligible = [
            deepcopy(r)
            for r in self._records
            if (
                r["patient_id"]
                == identity["patient_id"]
                and r["visit_id"]
                != identity["visit_id"]
                and timestamp(
                    r["visit_started_at"]
                )
                < cutoff
                and timestamp(
                    r["available_at"]
                )
                <= cutoff
            )
        ]

        superseded = {
            key
            for r in eligible
            for key in r["supersedes"]
        }

        words = set(
            re.findall(
                r"\w+",
                query.casefold(),
            )
        )

        for row in eligible:
            row["status_as_of_visit"] = (
                "superseded"
                if row["memory_id"]
                in superseded
                else "historical"
            )

            row["retrieval_score"] = len(
                words
                & set(
                    re.findall(
                        r"\w+",
                        row["text"].casefold(),
                    )
                )
            )

        # Canonical chronological order.
        eligible.sort(
            key=lambda r: (
                timestamp(
                    r["available_at"]
                ),
                r["memory_id"],
            )
        )

        if mode == "none":
            selected = []

        elif mode == "full_history":
            # If no context budget is used, preserve the original
            # full chronological history.
            #
            # If a context budget is provided, this becomes
            # Budgeted Full History:
            #
            # - all eligible history remains the candidate pool
            # - relevance score is NOT used
            # - most recent history is inserted first
            # - records are admitted until max_chars is reached
            #
            # This gives a realistic non-retrieval baseline while
            # remaining executable under a finite model context.
            if max_chars is None:
                selected = eligible
            else:
                selected = sorted(
                    eligible,
                    key=lambda r: (
                        -timestamp(
                            r["available_at"]
                        ).timestamp(),
                        r["memory_id"],
                    ),
                )

        elif mode == "summary":
            # Extractive baseline:
            # most recent non-superseded source per kind.
            #
            # Preserve exact text and IDs rather than generating
            # a new medical summary.
            latest = {}

            for row in eligible:
                if (
                    row[
                        "status_as_of_visit"
                    ]
                    != "superseded"
                ):
                    latest[
                        row["kind"]
                    ] = row

            selected = sorted(
                latest.values(),
                key=lambda r: (
                    -timestamp(
                        r["available_at"]
                    ).timestamp(),
                    r["memory_id"],
                ),
            )[:top_k]

        elif mode == "semantic":
            if embeddings is None:
                raise ValueError(
                    "Semantic retrieval requires "
                    "an embedding artifact"
                )

            from app.core.memory_evaluation import (
                visit_key,
            )

            candidates = [
                r
                for r in eligible
                if r[
                    "status_as_of_visit"
                ]
                != "superseded"
            ]

            scores = embeddings.scores(
                candidates,
                query,
                visit_key(identity),
            )

            for row in candidates:
                row[
                    "retrieval_score"
                ] = scores[
                    row["memory_id"]
                ]

            selected = sorted(
                [
                    r
                    for r in candidates
                    if r[
                        "retrieval_score"
                    ]
                    > 0
                ],
                key=lambda r: (
                    -r[
                        "retrieval_score"
                    ],
                    -timestamp(
                        r[
                            "available_at"
                        ]
                    ).timestamp(),
                    r[
                        "memory_id"
                    ],
                ),
            )[:top_k]

        else:
            # Selective lexical retrieval.
            selected = [
                r
                for r in eligible
                if (
                    r[
                        "status_as_of_visit"
                    ]
                    != "superseded"
                    and r[
                        "retrieval_score"
                    ]
                    > 0
                )
            ]

            selected.sort(
                key=lambda r: (
                    -r[
                        "retrieval_score"
                    ],
                    -timestamp(
                        r[
                            "available_at"
                        ]
                    ).timestamp(),
                    r[
                        "memory_id"
                    ],
                )
            )

            selected = selected[
                :top_k
            ]

        unbudgeted_count = len(
            selected
        )

        budgeted = []
        size = 2
        # JSON list brackets, in characters.
        # This is not a tokenizer-based token count.

        for row in selected:
            added = len(
                json.dumps(
                    row,
                    ensure_ascii=False,
                )
            )

            if budgeted:
                added += 2

            if (
                max_chars is None
                or size + added
                <= max_chars
            ):
                budgeted.append(
                    row
                )
                size += added

        selected = budgeted

        if (
            mode == "full_history"
            and max_chars is not None
        ):
            selection_method = (
                "budgeted_full_history_recent_first"
            )
        else:
            selection_method = {
                "selective":
                    "lexical_overlap_then_recency",
                "summary":
                    "latest_source_per_kind",
                "semantic":
                    "cosine_similarity",
            }.get(
                mode,
                mode,
            )

        return {
            "mode": mode,
            "as_of":
                identity[
                    "started_at"
                ],
            "records":
                selected,
            "conflicts":
                detect_conflicts(
                    selected
                ),
            "eligible_count":
                len(
                    eligible
                ),
            "selected_count":
                len(
                    selected
                ),
            "selection_method":
                selection_method,
            "max_chars":
                max_chars,
            "records_json_chars":
                size,
            "budget_excluded_count":
                (
                    unbudgeted_count
                    - len(
                        selected
                    )
                ),
            "embedding_artifact_sha256":
                (
                    embeddings.fingerprint
                    if mode
                    == "semantic"
                    else None
                ),
            "interpretation":
                (
                    "Historical observations and prior opinions, "
                    "not current confirmed diagnoses."
                ),
        }

    def ingest_completed_visit(
        self,
        runtime,
    ):
        if (
            not runtime.is_completed
            or runtime.final_diagnosis_min
            is None
        ):
            raise ValueError(
                "Only completed visits can be committed "
                "to longitudinal memory"
            )

        identity = visit_identity(
            runtime.case_data
        )

        if any(
            r["patient_id"]
            == identity["patient_id"]
            and r["visit_id"]
            == identity["visit_id"]
            for r in self._records
        ):
            raise ValueError(
                "Visit already committed"
            )

        end = (
            timestamp(
                identity[
                    "started_at"
                ]
            )
            + timedelta(
                minutes=(
                    runtime.final_diagnosis_min
                    - runtime.arrival_time_min
                )
            )
        )

        def observed_time(minute):
            if minute is None:
                return end.isoformat()

            if (
                type(minute) is not int
                or not (
                    runtime.arrival_time_min
                    <= minute
                    <= runtime.final_diagnosis_min
                )
            ):
                raise ValueError(
                    "Invalid observation minute"
                )

            return (
                timestamp(
                    identity[
                        "started_at"
                    ]
                )
                + timedelta(
                    minutes=(
                        minute
                        - runtime.arrival_time_min
                    )
                )
            ).isoformat()

        facts = []

        for i, item in enumerate(
            runtime.question_history
        ):
            if (
                item.get(
                    "answer_status"
                )
                != "unknown"
                and informative(
                    item.get(
                        "answer",
                        "",
                    )
                )
            ):
                facts.append(
                    (
                        f"history:{i}",
                        "history",
                        item["answer"],
                        observed_time(
                            item.get(
                                "observed_minute"
                            )
                        ),
                    )
                )

        for i, finding in enumerate(
            runtime.objective_findings
        ):
            if informative(
                str(
                    finding
                ).split(
                    ":",
                    1,
                )[-1]
            ):
                result = next(
                    (
                        r
                        for r
                        in runtime.test_results
                        if str(
                            finding
                        ).startswith(
                            str(
                                r.get(
                                    "test_name"
                                )
                            )
                            + ":"
                        )
                    ),
                    {},
                )

                facts.append(
                    (
                        f"finding:{i}",
                        "objective_finding",
                        str(
                            finding
                        ),
                        observed_time(
                            result.get(
                                "observed_minute"
                            )
                        ),
                    )
                )

        if informative(
            runtime.assessment_summary
        ):
            status = (
                "unresolved"
                if "diagnosis_unresolved"
                in runtime.alerts
                else "reported_not_verified"
            )

            facts.append(
                (
                    "assessment",
                    "prior_assessment",
                    (
                        f"[{status}] "
                        f"{runtime.assessment_summary}"
                    ),
                    end.isoformat(),
                )
            )

        for i, treatment in enumerate(
            runtime.interventions
        ):
            facts.append(
                (
                    f"intervention:{i}",
                    "intervention",
                    (
                        f"Administered "
                        f"{treatment['id']}; "
                        "this does not establish "
                        "continued medication use."
                    ),
                    observed_time(
                        treatment.get(
                            "time_min"
                        )
                    ),
                )
            )

        pending = []

        for (
            source,
            kind,
            text,
            observed,
        ) in facts:
            pending.append(
                {
                    "memory_id":
                        json.dumps(
                            [
                                identity[
                                    "patient_id"
                                ],
                                identity[
                                    "visit_id"
                                ],
                                source,
                            ]
                        ),
                    "patient_id":
                        identity[
                            "patient_id"
                        ],
                    "visit_id":
                        identity[
                            "visit_id"
                        ],
                    "visit_started_at":
                        identity[
                            "started_at"
                        ],
                    "observed_at":
                        observed,
                    "available_at":
                        observed,
                    "source_id":
                        source,
                    "kind":
                        kind,
                    "text":
                        text,
                    "supersedes":
                        [],
                }
            )

        validated = PatientMemoryStore(
            [
                *self._records,
                *pending,
            ]
        )

        self._records = (
            validated._records
        )

        return len(
            pending
        )