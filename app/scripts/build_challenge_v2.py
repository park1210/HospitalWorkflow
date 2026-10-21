import json
from pathlib import Path


ROOT = Path("app/data/challenge_v2")

PATIENT_COUNT = 20

NOISE_TEXTS = [
    "Remote ankle injury resolved.",
    "Dental cleaning completed.",
    "Travel paperwork reviewed.",
    "Seasonal allergy symptoms resolved.",
    "Routine vaccination completed.",
    "Minor wrist strain resolved.",
]


def write_json(name, value):
    ROOT.mkdir(parents=True, exist_ok=True)

    path = ROOT / name

    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"written: {path}")


def visit_key(patient_id, visit_id):
    return json.dumps(
        [
            patient_id,
            visit_id,
        ],
        ensure_ascii=False,
    )


def memory_record(
    memory_id,
    patient_id,
    visit_id,
    date,
    text,
    *,
    supersedes=None,
):
    return {
        "memory_id": memory_id,
        "patient_id": patient_id,
        "visit_id": visit_id,
        "visit_started_at": date,
        "observed_at": date,
        "available_at": date,
        "source_id": "synthetic-challenge-v2",
        "kind": "history",
        "text": text,
        "supersedes": supersedes or [],
    }


def build_case(
    *,
    patient_id,
    visit_id,
    started_at,
    diagnosis,
    indicator_present,
    group,
):
    finding = (
        "Synthetic A finding"
        if diagnosis == "Synthetic A"
        else "Synthetic B finding"
    )

    # 일부 그룹은 현재 history와 gold diagnosis가
    # 완전히 일치하지 않도록 만들어 단순 shortcut을 줄인다.
    if group == "memory_critical":
        history = (
            "Current symptoms are nonspecific. "
            "The patient cannot clearly distinguish whether the prior pattern has returned."
        )

    elif group == "conflict":
        history = (
            "The patient reports an uncertain recurrence of the prior synthetic symptom pattern."
        )

    elif group == "paraphrase":
        history = (
            "The current complaint resembles an earlier recurring marker episode."
        )

    elif group == "distractors":
        history = (
            "The patient reports general discomfort with no clear identifying feature."
        )

    else:
        history = (
            "Synthetic indicator is present."
            if indicator_present
            else "Synthetic indicator is absent."
        )

    chief = {
        "memory_critical": "Recurrent nonspecific synthetic complaint",
        "conflict": "Conflicting prior synthetic history",
        "paraphrase": "Recurring marker concern",
        "distractors": "Synthetic discomfort with unrelated history",
        "baseline": "Prior synthetic indicator discomfort",
    }[group]

    return {
        "case_id": f"{patient_id}-{visit_id}",
        "longitudinal": {
            "patient_id": patient_id,
            "visit_id": visit_id,
            "started_at": started_at,
        },
        "doctor_visible_info": {
            "chief_complaint": chief,
            "initial_vitals": {
                "spo2": 98,
            },
        },
        "patient_visible_info": {
            "history": history,
        },
        "available_tests": [
            "T",
        ],
        "hidden_test_results": {
            "T": {
                "result": finding,
            },
        },
        "resource_profile": {
            "test_resources": {
                "T": "lab_slot",
            },
            "test_occupancy": {
                "T": 1,
            },
            "test_turnaround": {
                "T": 1,
            },
        },
    }


def build_patient(index):
    patient_id = f"challenge-v2-test-p{index:02d}"

    # 20명 = 4 groups x 5명
    group_index = (index - 1) // 5

    groups = [
        "memory_critical",
        "distractors",
        "conflict",
        "paraphrase",
    ]

    group = groups[group_index]

    # 각 환자 v1 / v2에서 diagnosis가 바뀌도록 설계.
    # 홀수 patient:
    #   v1 A, v2 B
    # 짝수 patient:
    #   v1 B, v2 A
    if index % 2 == 1:
        diagnosis_v1 = "Synthetic A"
        diagnosis_v2 = "Synthetic B"
    else:
        diagnosis_v1 = "Synthetic B"
        diagnosis_v2 = "Synthetic A"

    indicator_v1 = diagnosis_v1 == "Synthetic A"
    indicator_v2 = diagnosis_v2 == "Synthetic A"

    cases = [
        build_case(
            patient_id=patient_id,
            visit_id="v1",
            started_at="2026-02-01T00:00:00Z",
            diagnosis=diagnosis_v1,
            indicator_present=indicator_v1,
            group=group,
        ),
        build_case(
            patient_id=patient_id,
            visit_id="v2",
            started_at="2026-03-01T00:00:00Z",
            diagnosis=diagnosis_v2,
            indicator_present=indicator_v2,
            group=group,
        ),
    ]

    labels = {
        visit_key(patient_id, "v1"): diagnosis_v1,
        visit_key(patient_id, "v2"): diagnosis_v2,
    }

    memories = []
    annotations = {}

    indicator_id = f"{patient_id}-indicator"

    # 과거 v0의 relevant memory.
    #
    # diagnosis label 자체를 직접 쓰지 않고
    # synthetic context만 제공한다.
    initial_memory_text = (
        "A prior episode contained marker pattern alpha."
        if index % 2 == 1
        else "A prior episode contained marker pattern beta."
    )

    memories.append(
        memory_record(
            indicator_id,
            patient_id,
            "v0",
            "2026-01-01T00:00:00Z",
            initial_memory_text,
        )
    )

    # distractors
    for noise_index in range(3):
        memories.append(
            memory_record(
                f"{patient_id}-noise-{noise_index}",
                patient_id,
                "v0",
                "2026-01-01T00:00:00Z",
                NOISE_TEXTS[
                    (index + noise_index)
                    % len(NOISE_TEXTS)
                ],
            )
        )

    stale_ids_v1 = []
    stale_ids_v2 = []

    relevant_v1 = [
        indicator_id,
    ]

    relevant_v2 = [
        indicator_id,
    ]

    # ---------------------------------------------------------
    # Memory-critical
    #
    # v1/v2 current presentation은 모호하고,
    # longitudinal memory가 가장 유용한 조건.
    # ---------------------------------------------------------
    if group == "memory_critical":
        memories.append(
            memory_record(
                f"{patient_id}-pattern-detail",
                patient_id,
                "v0",
                "2026-01-01T00:00:00Z",
                (
                    "Previous episodes with marker pattern alpha "
                    "were followed by objective pattern A."
                    if index % 2 == 1
                    else
                    "Previous episodes with marker pattern beta "
                    "were followed by objective pattern B."
                ),
            )
        )

        relevant_v1.append(
            f"{patient_id}-pattern-detail"
        )

        relevant_v2.append(
            f"{patient_id}-pattern-detail"
        )

    # ---------------------------------------------------------
    # Conflict
    #
    # 서로 충돌하는 memory를 함께 제공.
    # ---------------------------------------------------------
    elif group == "conflict":
        positive_id = f"{patient_id}-positive"
        negative_id = f"{patient_id}-negative"

        memories.extend(
            [
                memory_record(
                    positive_id,
                    patient_id,
                    "v0",
                    "2026-01-01T00:00:00Z",
                    "The patient previously reported the recurring marker.",
                ),
                memory_record(
                    negative_id,
                    patient_id,
                    "v0",
                    "2026-01-01T00:00:00Z",
                    "The patient previously denied the recurring marker.",
                ),
            ]
        )

        relevant_v1.extend(
            [
                positive_id,
                negative_id,
            ]
        )

        relevant_v2.extend(
            [
                positive_id,
                negative_id,
            ]
        )

    # ---------------------------------------------------------
    # Paraphrase
    #
    # current query와 memory wording을 다르게 해
    # lexical retrieval을 어렵게 만든다.
    # ---------------------------------------------------------
    elif group == "paraphrase":
        paraphrase_id = (
            f"{patient_id}-semantic-marker"
        )

        memories.append(
            memory_record(
                paraphrase_id,
                patient_id,
                "v0",
                "2026-01-01T00:00:00Z",
                "Earlier episodes showed a recurrent historical pattern.",
            )
        )

        relevant_v1 = [
            paraphrase_id,
        ]

        relevant_v2 = [
            paraphrase_id,
        ]

    # ---------------------------------------------------------
    # Distractors
    #
    # relevant memory 1개 + 여러 unrelated memories.
    # ---------------------------------------------------------
    elif group == "distractors":
        pass

    # ---------------------------------------------------------
    # 일부 환자에 superseded memory 추가.
    #
    # 전체 20명 중 5명 정도.
    # ---------------------------------------------------------
    if index % 4 == 0:
        update_id = f"{patient_id}-update"

        memories.append(
            memory_record(
                update_id,
                patient_id,
                "v1-history",
                "2026-02-15T00:00:00Z",
                "Updated prior marker information.",
                supersedes=[
                    indicator_id,
                ],
            )
        )

        relevant_v2 = [
            update_id
            if item == indicator_id
            else item
            for item in relevant_v2
        ]

        stale_ids_v2.append(
            indicator_id
        )

    # ---------------------------------------------------------
    # future sentinel
    #
    # 절대 현재 visit에서 보여서는 안 되는 미래 memory.
    # ---------------------------------------------------------
    memories.append(
        memory_record(
            f"{patient_id}-future",
            patient_id,
            "v3",
            "2027-01-01T00:00:00Z",
            "Future sentinel must never be visible.",
        )
    )

    annotations[
        visit_key(
            patient_id,
            "v1",
        )
    ] = {
        "relevant_memory_ids": relevant_v1,
        "stale_memory_ids": stale_ids_v1,
    }

    annotations[
        visit_key(
            patient_id,
            "v2",
        )
    ] = {
        "relevant_memory_ids": relevant_v2,
        "stale_memory_ids": stale_ids_v2,
    }

    scenarios = [
        {
            "patient_id": patient_id,
            "visit_id": "v1",
            "split": "test",
            "group": group,
        },
        {
            "patient_id": patient_id,
            "visit_id": "v2",
            "split": "test",
            "group": group,
        },
    ]

    return {
        "cases": cases,
        "labels": labels,
        "memory": memories,
        "annotations": annotations,
        "scenarios": scenarios,
    }


def build_registry():
    return {
        "schema_version": 1,
        "agents": [
            {
                "agent_id": "local-er",
                "role": "er",
                "department": "",
                "model": "llama3.2:3b",
                "version": "challenge-v2-er",
                "keywords": [],
            },
            {
                "agent_id": "local-neurology",
                "role": "specialty",
                "department": "neurology",
                "model": "qwen-neurology:latest",
                "version": "challenge-v2-neurology",
                "keywords": [
                    "synthetic",
                    "marker",
                    "pattern",
                    "recurrent",
                ],
            },
            {
                "agent_id": "local-pulmonology",
                "role": "specialty",
                "department": "pulmonology",
                "model": "qwen-pulmonology:latest",
                "version": "challenge-v2-pulmonology",
                "keywords": [
                    "synthetic",
                    "discomfort",
                    "pattern",
                    "recurring",
                ],
            },
        ],
    }


def build_routing_utility(registry):
    """
    Pre-existing toy routing utility.

    각 training decision은 동일한 observation에서
    모든 registered specialty agent를 비교한다.

    challenge_v2 evaluation patient와 겹치지 않는다.
    """

    obs0_tokens = [
        "synthetic",
        "marker",
        "pattern",
        "recurrent",
    ]

    obs1_tokens = [
        "synthetic",
        "discomfort",
        "recurring",
        "pattern",
    ]

    return {
        "schema_version": 1,
        "method": "jaccard_beta_v1",
        "registry": registry,
        "weights": {
            "accuracy": 1,
            "cost": 0,
            "latency": 0.001,
        },
        "min_samples": 2,
        "samples": [
            # -------------------------------------------------
            # Training observation 0
            # 동일 patient_id + decision_id + 동일 tokens
            # -------------------------------------------------
            {
                "patient_id": "routing-train-0",
                "decision_id": "routing-train-0-probe",
                "agent_id": "local-neurology",
                "correct": True,
                "cost": 0.0,
                "latency_seconds": 8.0,
                "tokens": obs0_tokens,
            },
            {
                "patient_id": "routing-train-0",
                "decision_id": "routing-train-0-probe",
                "agent_id": "local-pulmonology",
                "correct": False,
                "cost": 0.0,
                "latency_seconds": 10.0,
                "tokens": obs0_tokens,
            },

            # -------------------------------------------------
            # Training observation 1
            # 역시 모든 specialty가 같은 observation에 존재
            # -------------------------------------------------
            {
                "patient_id": "routing-train-1",
                "decision_id": "routing-train-1-probe",
                "agent_id": "local-neurology",
                "correct": False,
                "cost": 0.0,
                "latency_seconds": 9.0,
                "tokens": obs1_tokens,
            },
            {
                "patient_id": "routing-train-1",
                "decision_id": "routing-train-1-probe",
                "agent_id": "local-pulmonology",
                "correct": True,
                "cost": 0.0,
                "latency_seconds": 11.0,
                "tokens": obs1_tokens,
            },
        ],
    }



def build_voi_model():
    """
    기존 two-diagnosis VoI 구조를 유지한다.

    중요한 점:
    - diagnostic label을 patient observation에 직접 넣지 않는다.
    - objective test T는 강한 evidence.
    - interview와 memory는 중간 정도 evidence.
    """

    return {
        "schema_version": 1,
        "model_id": "synthetic-two-diagnosis-voi-v2",
        "revision": "v2",
        "provenance": {
            "synthetic": True,
            "review_status": "unreviewed",
            "training_patients": [
                "voi-training-0",
                "voi-training-1",
            ],
            "assumptions": [
                "Fixed finite diagnosis universe",
                "Outcomes conditionally independent given diagnosis",
                "Exact categorical outcome text",
                "Costs are synthetic utility units, not clinical prices",
            ],
        },
        "diagnoses": {
            "Synthetic A": "general_medicine",
            "Synthetic B": "general_medicine",
        },
        "prior": {
            "Synthetic A": 0.5,
            "Synthetic B": 0.5,
        },
        "terminal_utility": {
            "Synthetic A": {
                "Synthetic A": 1,
                "Synthetic B": 0,
            },
            "Synthetic B": {
                "Synthetic A": 0,
                "Synthetic B": 1,
            },
        },
        "cost_weights": {
            "money": 1,
            "minutes": 0,
            "tokens": 0,
        },
        "stop_probability": 0.95,
        "horizon": 1,
        "actions": [
            {
                "id": "test-t",
                "type": "request_test",
                "target": "T",
                "cost": {
                    "money": 0.05,
                    "minutes": 0,
                    "tokens": 0,
                },
                "outcomes": [
                    {
                        "id": "a",
                        "likelihood": {
                            "Synthetic A": 0.90,
                            "Synthetic B": 0.10,
                        },
                        "observation": {
                            "source": "objective_findings",
                            "text": "T: Synthetic A finding",
                        },
                        "supports_diagnoses": [
                            "Synthetic A",
                        ],
                    },
                    {
                        "id": "b",
                        "likelihood": {
                            "Synthetic A": 0.10,
                            "Synthetic B": 0.90,
                        },
                        "observation": {
                            "source": "objective_findings",
                            "text": "T: Synthetic B finding",
                        },
                        "supports_diagnoses": [
                            "Synthetic B",
                        ],
                    },
                ],
            },
            {
                "id": "interview",
                "type": "ask_patient",
                "target": "Does this resemble your previous episode?",
                "cost": {
                    "money": 0.02,
                    "minutes": 0,
                    "tokens": 0,
                },
                "outcomes": [
                    {
                        "id": "yes",
                        "likelihood": {
                            "Synthetic A": 0.60,
                            "Synthetic B": 0.40,
                        },
                        "observation": {
                            "source": "history",
                            "text": "The current complaint resembles an earlier recurring marker episode.",
                        },
                        "supports_diagnoses": [],
                    },
                    {
                        "id": "no",
                        "likelihood": {
                            "Synthetic A": 0.40,
                            "Synthetic B": 0.60,
                        },
                        "observation": {
                            "source": "history",
                            "text": "The current complaint does not resemble the earlier episode.",
                        },
                        "supports_diagnoses": [],
                    },
                ],
            },
            {
                "id": "memory-alpha",
                "type": "retrieve_memory",
                "target": "longitudinal",
                "cost": {
                    "money": 0.01,
                    "minutes": 0,
                    "tokens": 0,
                },
                "outcomes": [
                    {
                        "id": "alpha",
                        "likelihood": {
                            "Synthetic A": 0.70,
                            "Synthetic B": 0.30,
                        },
                        "observation": {
                            "source": "memory",
                            "text": "A prior episode contained marker pattern alpha.",
                        },
                        "supports_diagnoses": [],
                    },
                    {
                        "id": "beta",
                        "likelihood": {
                            "Synthetic A": 0.30,
                            "Synthetic B": 0.70,
                        },
                        "observation": {
                            "source": "memory",
                            "text": "A prior episode contained marker pattern beta.",
                        },
                        "supports_diagnoses": [],
                    },
                ],
            },
            {
                "id": "consult-neuro",
                "type": "consult_specialty",
                "target": "neurology",
                "cost": {
                    "money": 0.20,
                    "minutes": 0,
                    "tokens": 0,
                },
                "outcomes": [
                    {
                        "id": "a",
                        "likelihood": {
                            "Synthetic A": 0.75,
                            "Synthetic B": 0.25,
                        },
                        "observation": {
                            "source": "consults",
                            "text": "Neurology favors synthetic pattern A.",
                        },
                        "supports_diagnoses": [],
                    },
                    {
                        "id": "b",
                        "likelihood": {
                            "Synthetic A": 0.25,
                            "Synthetic B": 0.75,
                        },
                        "observation": {
                            "source": "consults",
                            "text": "Neurology favors synthetic pattern B.",
                        },
                        "supports_diagnoses": [],
                    },
                ],
            },
        ],
    }


def build_prices():
    return {
        "llama3.2:3b": {
            "input_per_million": 0,
            "output_per_million": 0,
            "currency": "USD",
        },
        "qwen-neurology:latest": {
            "input_per_million": 0,
            "output_per_million": 0,
            "currency": "USD",
        },
        "qwen-pulmonology:latest": {
            "input_per_million": 0,
            "output_per_million": 0,
            "currency": "USD",
        },
    }


def build_plan():
    return {
        "schema_version": 1,
        "provenance": {
            "synthetic": True,
            "review_status": "unreviewed",
            "scope": (
                "expanded designed challenge cases; "
                "not clinical evidence"
            ),
            "split": "test_v2",
            "routing": (
                "pre-existing synthetic routing utility; "
                "not trained on challenge-v2 patients"
            ),
        },
        "repeats": 1,
        "retrieved_mode": "selective",
        "top_k": 1,
        "minute_limit": 30,
        "inputs": {
            "cases": "cases_test.json",
            "labels": "labels_test.json",
            "memory": "memory.json",
            "annotations": "annotations_test.json",
            "registry": "registry.json",
            "routing_utility": "routing_utility.json",
            "prices": "prices.json",
            "voi_model": "model.json",
            "scenarios": "scenarios.json",
        },
    }


def main():
    cases = []
    labels = {}
    memory = []
    annotations = {}
    scenarios = []

    for index in range(
        1,
        PATIENT_COUNT + 1,
    ):
        patient = build_patient(
            index
        )

        cases.extend(
            patient[
                "cases"
            ]
        )

        labels.update(
            patient[
                "labels"
            ]
        )

        memory.extend(
            patient[
                "memory"
            ]
        )

        annotations.update(
            patient[
                "annotations"
            ]
        )

        scenarios.extend(
            patient[
                "scenarios"
            ]
        )

    registry = build_registry()

    routing_utility = (
        build_routing_utility(
            registry
        )
    )

    model = build_voi_model()

    prices = build_prices()

    plan = build_plan()

    write_json(
        "cases_test.json",
        cases,
    )

    write_json(
        "labels_test.json",
        labels,
    )

    write_json(
        "memory.json",
        {
            "schema_version": 1,
            "records": memory,
        },
    )

    write_json(
        "annotations_test.json",
        annotations,
    )

    write_json(
        "scenarios.json",
        scenarios,
    )

    write_json(
        "registry.json",
        registry,
    )

    write_json(
        "routing_utility.json",
        routing_utility,
    )

    write_json(
        "model.json",
        model,
    )

    write_json(
        "prices.json",
        prices,
    )

    write_json(
        "plan_test.json",
        plan,
    )

    readme = f"""# Longitudinal challenge benchmark v2

Synthetic, unreviewed expanded challenge set.

- Patients: {PATIENT_COUNT}
- Visits per patient: 2
- Total evaluated visits: {PATIENT_COUNT * 2}

Groups:
- memory_critical: 10 visits
- distractors: 10 visits
- conflict: 10 visits
- paraphrase: 10 visits

This dataset is intended to investigate whether the ceiling effect
observed in challenge_v1 persists after increasing independent visits.

It is not clinical evidence and has not been clinically reviewed.

Important:
Do not tune the policy after inspecting final test results.
"""

    (
        ROOT
        / "README.md"
    ).write_text(
        readme,
        encoding="utf-8",
    )

    print()
    print(
        f"Done: {len(cases)} visits"
    )
    print(
        f"Patients: {PATIENT_COUNT}"
    )
    print(
        f"Labels: {len(labels)}"
    )
    print(
        f"Annotations: {len(annotations)}"
    )
    print(
        f"Memory records: {len(memory)}"
    )


if __name__ == "__main__":
    main()