import json
from pathlib import Path


ROOT = Path("app/data/challenge_v4")

DIAG_A = "Synthetic A"
DIAG_B = "Synthetic B"

N_PER_GROUP = 10

STOP_PROBABILITY = 0.95

# Decisive finding은 불리한 prior에서도 0.95를 넘도록 강하게 설정.
DECISIVE_HIGH = 0.999
DECISIVE_LOW = 0.001


# ============================================================
# Common utilities
# ============================================================

def write_json(filename, value):
    ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = ROOT / filename

    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("written:", path)


def visit_key(patient_id, visit_id):
    return json.dumps(
        [patient_id, visit_id],
        ensure_ascii=False,
    )


def test_result(text):
    return {
        "result": text,
    }


def memory_record(
    memory_id,
    patient_id,
    text,
    *,
    visit_id="v0",
    started_at="2026-01-01T00:00:00Z",
    available_at="2026-01-01T00:00:00Z",
):
    return {
        "memory_id": memory_id,
        "patient_id": patient_id,
        "visit_id": visit_id,
        "visit_started_at": started_at,
        "observed_at": started_at,
        "available_at": available_at,
        "source_id": "synthetic-challenge-v4",
        "kind": "history",
        "text": text,
        "supersedes": [],
    }


def base_resources(test_names):
    return {
        "test_resources": {
            test_name: "lab_slot"
            for test_name in test_names
        },
        "test_occupancy": {
            test_name: 1
            for test_name in test_names
        },
        "test_turnaround": {
            test_name: 1
            for test_name in test_names
        },
    }


def base_case(
    patient_id,
    complaint,
    history,
    tests,
    access,
    results,
):
    return {
        "case_id": f"{patient_id}-v1",

        "longitudinal": {
            "patient_id": patient_id,
            "visit_id": "v1",
            "started_at": "2026-03-01T00:00:00Z",
        },

        "doctor_visible_info": {
            "chief_complaint": complaint,

            "initial_vitals": {
                "spo2": 98,
            },
        },

        "patient_visible_info": {
            "history": history,
        },

        "available_tests": tests,

        "test_access": access,

        "hidden_test_results": {
            name: test_result(value)
            for name, value in results.items()
        },

        "resource_profile": base_resources(
            tests
        ),
    }


# ============================================================
# Baseline
# ============================================================

def build_baseline_case(
    patient_id,
    diagnosis,
):
    """
    기본 control.

    하나의 current objective result만으로
    A/B가 명확히 구분된다.

    Memory/Routing/VoI 없이도 풀 수 있어야 한다.
    """

    tests = [
        "T_BASE",
    ]

    if diagnosis == DIAG_A:
        result = (
            "Diagnostic result supports Synthetic A "
            "and does not support Synthetic B"
        )
    else:
        result = (
            "Diagnostic result supports Synthetic B "
            "and does not support Synthetic A"
        )

    return base_case(
        patient_id,

        complaint=(
            "Acute synthetic diagnostic concern"
        ),

        history=(
            "No relevant longitudinal history is required "
            "for this control case."
        ),

        tests=tests,

        access={
            "T_BASE": [
                "er",
                "neurology",
                "pulmonology",
            ],
        },

        results={
            "T_BASE": result,
        },
    )


# ============================================================
# Memory-critical
# ============================================================

def build_memory_case(
    patient_id,
    diagnosis,
):
    """
    Current evidence만으로는 A/B가 모두 가능.

    T_CONTEXT:
      - 현재 objective abnormality 존재
      - A/B 자체는 구분하지 않음

    relevant longitudinal memory:
      - A/B를 구분

    따라서 current objective evidence + memory가 필요.
    """

    tests = [
        "T_CONTEXT",
    ]

    return base_case(
        patient_id,

        complaint=(
            "Recurrent synthetic syndrome with a pattern "
            "similar to a previous documented episode"
        ),

        history=(
            "The patient remembers having a similar previous "
            "episode but cannot recall which longitudinal "
            "pattern was documented."
        ),

        tests=tests,

        access={
            "T_CONTEXT": [
                "er",
                "neurology",
                "pulmonology",
            ],
        },

        results={
            "T_CONTEXT": (
                "Current objective finding is compatible "
                "with both Synthetic A and Synthetic B"
            ),
        },
    )


# ============================================================
# Routing-critical
# ============================================================

def build_routing_case(
    patient_id,
    diagnosis,
):
    """
    ER-accessible screen은 진단 불가능.

    A:
        neurology route -> T_NEURO -> decisive

    B:
        pulmonology route -> T_PULM -> decisive

    ER은 specialty-specific test에 접근 불가.
    """

    tests = [
        "T_SCREEN",
        "T_NEURO",
        "T_PULM",
    ]

    if diagnosis == DIAG_A:

        complaint = (
            "Recurrent focal sensory neurologic pattern "
            "with intermittent unilateral symptoms"
        )

        neuro_result = (
            "Neurology-specific result supports Synthetic A "
            "and does not support Synthetic B"
        )

        pulm_result = (
            "Pulmonology-specific result is nondiagnostic"
        )

    else:

        complaint = (
            "Recurrent respiratory breathing pattern "
            "with intermittent exertional symptoms"
        )

        neuro_result = (
            "Neurology-specific result is nondiagnostic"
        )

        pulm_result = (
            "Pulmonology-specific result supports Synthetic B "
            "and does not support Synthetic A"
        )

    return base_case(
        patient_id,

        complaint=complaint,

        history=(
            "Initial ER information does not provide "
            "a decisive disease-specific finding."
        ),

        tests=tests,

        access={
            "T_SCREEN": [
                "er",
                "neurology",
                "pulmonology",
            ],

            "T_NEURO": [
                "neurology",
            ],

            "T_PULM": [
                "pulmonology",
            ],
        },

        results={
            "T_SCREEN": (
                "Nondiscriminative screening abnormality; "
                "specialty evaluation is required"
            ),

            "T_NEURO": neuro_result,

            "T_PULM": pulm_result,
        },
    )


# ============================================================
# VoI-critical
# ============================================================

def build_voi_case(
    patient_id,
    diagnosis,
):
    """
    T_LOW:
        약한 정보만 제공.
        finalization support 없음.

    T_HIGH:
        결정적 정보.
        단일 검사로 finalization 가능.

    B3 LLM policy와 B4 VoI policy의
    정보 획득 선택 차이를 평가한다.
    """

    tests = [
        "T_LOW",
        "T_HIGH",
    ]

    if diagnosis == DIAG_A:

        low = (
            "Weak tendency toward Synthetic A, "
            "insufficient for final diagnosis"
        )

        high = (
            "High-confidence objective result supports "
            "Synthetic A and does not support Synthetic B"
        )

    else:

        low = (
            "Weak tendency toward Synthetic B, "
            "insufficient for final diagnosis"
        )

        high = (
            "High-confidence objective result supports "
            "Synthetic B and does not support Synthetic A"
        )

    return base_case(
        patient_id,

        complaint=(
            "Synthetic diagnostic uncertainty requiring "
            "selection between low-value and high-value testing"
        ),

        history=(
            "Initial history is compatible with both candidate diagnoses."
        ),

        tests=tests,

        access={
            "T_LOW": [
                "er",
                "neurology",
                "pulmonology",
            ],

            "T_HIGH": [
                "er",
                "neurology",
                "pulmonology",
            ],
        },

        results={
            "T_LOW": low,
            "T_HIGH": high,
        },
    )


# ============================================================
# Registry
# ============================================================

def build_registry():
    return {
        "schema_version": 1,

        "agents": [
            {
                "agent_id": "local-er",
                "role": "er",
                "department": "",
                "model": "llama3.2:3b",
                "version": "challenge-v4-er",
                "keywords": [],
            },

            {
                "agent_id": "local-neurology",
                "role": "specialty",
                "department": "neurology",
                "model": "qwen-neurology:latest",
                "version": "challenge-v4-neuro",

                "keywords": [
                    "focal",
                    "sensory",
                    "neurologic",
                    "neurology",
                    "unilateral",
                ],
            },

            {
                "agent_id": "local-pulmonology",
                "role": "specialty",
                "department": "pulmonology",
                "model": "qwen-pulmonology:latest",
                "version": "challenge-v4-pulm",

                "keywords": [
                    "respiratory",
                    "breathing",
                    "pulmonary",
                    "pulmonology",
                    "exertional",
                ],
            },
        ],
    }


# ============================================================
# Routing utility
# ============================================================

def build_routing_utility(
    registry,
):
    samples = []

    training_rows = [
        (
            "routing-train-neuro-01",
            [
                "recurrent",
                "focal",
                "sensory",
                "neurologic",
                "unilateral",
                "pattern",
            ],
            True,
            False,
        ),

        (
            "routing-train-neuro-02",
            [
                "focal",
                "sensory",
                "neurology",
                "pattern",
            ],
            True,
            False,
        ),

        (
            "routing-train-neuro-03",
            [
                "neurologic",
                "unilateral",
                "sensory",
                "concern",
            ],
            True,
            False,
        ),

        (
            "routing-train-pulm-01",
            [
                "recurrent",
                "respiratory",
                "breathing",
                "exertional",
                "pattern",
            ],
            False,
            True,
        ),

        (
            "routing-train-pulm-02",
            [
                "respiratory",
                "pulmonary",
                "breathing",
                "pattern",
            ],
            False,
            True,
        ),

        (
            "routing-train-pulm-03",
            [
                "pulmonary",
                "exertional",
                "breathing",
                "concern",
            ],
            False,
            True,
        ),
    ]

    for (
        patient_id,
        tokens,
        neuro_correct,
        pulm_correct,
    ) in training_rows:

        decision_id = (
            f"{patient_id}-decision"
        )

        samples.append(
            {
                "patient_id": patient_id,
                "decision_id": decision_id,
                "agent_id": "local-neurology",
                "correct": neuro_correct,
                "cost": 0.0,
                "latency_seconds": 8.0,
                "tokens": tokens,
            }
        )

        samples.append(
            {
                "patient_id": patient_id,
                "decision_id": decision_id,
                "agent_id": "local-pulmonology",
                "correct": pulm_correct,
                "cost": 0.0,
                "latency_seconds": 8.0,
                "tokens": tokens,
            }
        )

    return {
        "schema_version": 1,

        "method": "jaccard_beta_v1",

        "registry": registry,

        "weights": {
            "accuracy": 1.0,
            "cost": 0.0,
            "latency": 0.001,
        },

        "min_samples": 2,

        "samples": samples,
    }


# ============================================================
# VoI helpers
# ============================================================

def outcome(
    outcome_id,
    p_a,
    p_b,
    source,
    text,
    supports=None,
):
    return {
        "id": outcome_id,

        "likelihood": {
            DIAG_A: p_a,
            DIAG_B: p_b,
        },

        "observation": {
            "source": source,
            "text": text,
        },

        "supports_diagnoses": (
            supports
            if supports is not None
            else []
        ),
    }


def test_action(
    action_id,
    target,
    cost,
    outcomes,
):
    return {
        "id": action_id,
        "type": "request_test",
        "target": target,

        "cost": {
            "money": cost,
            "minutes": 0,
            "tokens": 0,
        },

        "outcomes": outcomes,
    }


# ============================================================
# VoI model
# ============================================================

def build_voi_model():

    actions = []

    # --------------------------------------------------------
    # Baseline
    # --------------------------------------------------------

    actions.append(
        test_action(
            "baseline-test",
            "T_BASE",
            0.02,
            [
                outcome(
                    "a",
                    DECISIVE_HIGH,
                    DECISIVE_LOW,
                    "objective_findings",
                    (
                        "T_BASE: Diagnostic result supports "
                        "Synthetic A and does not support Synthetic B"
                    ),
                    [DIAG_A],
                ),

                outcome(
                    "b",
                    DECISIVE_LOW,
                    DECISIVE_HIGH,
                    "objective_findings",
                    (
                        "T_BASE: Diagnostic result supports "
                        "Synthetic B and does not support Synthetic A"
                    ),
                    [DIAG_B],
                ),
            ],
        )
    )

    # --------------------------------------------------------
    # Memory contextual objective evidence
    # --------------------------------------------------------

    actions.append(
        test_action(
            "context-test",
            "T_CONTEXT",
            0.02,
            [
                outcome(
                    "present",
                    0.5,
                    0.5,
                    "objective_findings",
                    (
                        "T_CONTEXT: Current objective finding "
                        "is compatible with both Synthetic A "
                        "and Synthetic B"
                    ),
                    [
                        DIAG_A,
                        DIAG_B,
                    ],
                ),

                outcome(
                    "absent",
                    0.5,
                    0.5,
                    "objective_findings",
                    (
                        "T_CONTEXT: Current objective finding "
                        "is absent"
                    ),
                    [],
                ),
            ],
        )
    )

    # --------------------------------------------------------
    # Routing screen
    #
    # IMPORTANT:
    # screen 자체는 finalization evidence가 아님.
    # --------------------------------------------------------

    actions.append(
        test_action(
            "routing-screen",
            "T_SCREEN",
            0.01,
            [
                outcome(
                    "positive",
                    0.5,
                    0.5,
                    "objective_findings",
                    (
                        "T_SCREEN: Nondiscriminative screening "
                        "abnormality; specialty evaluation is required"
                    ),
                    [],
                ),

                outcome(
                    "negative",
                    0.5,
                    0.5,
                    "objective_findings",
                    (
                        "T_SCREEN: No useful disease-specific "
                        "information"
                    ),
                    [],
                ),
            ],
        )
    )

    # --------------------------------------------------------
    # Neurology-specific test
    # --------------------------------------------------------

    actions.append(
        test_action(
            "neuro-test",
            "T_NEURO",
            0.03,
            [
                outcome(
                    "a",
                    DECISIVE_HIGH,
                    DECISIVE_LOW,
                    "objective_findings",
                    (
                        "T_NEURO: Neurology-specific result "
                        "supports Synthetic A and does not "
                        "support Synthetic B"
                    ),
                    [DIAG_A],
                ),

                outcome(
                    "nondiagnostic",
                    DECISIVE_LOW,
                    DECISIVE_HIGH,
                    "objective_findings",
                    (
                        "T_NEURO: Neurology-specific result "
                        "is nondiagnostic"
                    ),
                    [],
                ),
            ],
        )
    )

    # --------------------------------------------------------
    # Pulmonology-specific test
    # --------------------------------------------------------

    actions.append(
        test_action(
            "pulm-test",
            "T_PULM",
            0.03,
            [
                outcome(
                    "nondiagnostic",
                    DECISIVE_HIGH,
                    DECISIVE_LOW,
                    "objective_findings",
                    (
                        "T_PULM: Pulmonology-specific result "
                        "is nondiagnostic"
                    ),
                    [],
                ),

                outcome(
                    "b",
                    DECISIVE_LOW,
                    DECISIVE_HIGH,
                    "objective_findings",
                    (
                        "T_PULM: Pulmonology-specific result "
                        "supports Synthetic B and does not "
                        "support Synthetic A"
                    ),
                    [DIAG_B],
                ),
            ],
        )
    )

    # --------------------------------------------------------
    # VoI low-value test
    #
    # 충분히 informative하지 않음.
    # finalization 지원도 없음.
    #
    # 비용을 HIGH보다 높게 둔 이유:
    # LOW -> HIGH 경로가 HIGH direct보다 비효율적이어야 함.
    # --------------------------------------------------------

    actions.append(
        test_action(
            "low-information-test",
            "T_LOW",
            0.08,
            [
                outcome(
                    "weak-a",
                    0.60,
                    0.40,
                    "objective_findings",
                    (
                        "T_LOW: Weak tendency toward Synthetic A, "
                        "insufficient for final diagnosis"
                    ),
                    [],
                ),

                outcome(
                    "weak-b",
                    0.40,
                    0.60,
                    "objective_findings",
                    (
                        "T_LOW: Weak tendency toward Synthetic B, "
                        "insufficient for final diagnosis"
                    ),
                    [],
                ),
            ],
        )
    )

    # --------------------------------------------------------
    # VoI high-value test
    # --------------------------------------------------------

    actions.append(
        test_action(
            "high-information-test",
            "T_HIGH",
            0.04,
            [
                outcome(
                    "a",
                    DECISIVE_HIGH,
                    DECISIVE_LOW,
                    "objective_findings",
                    (
                        "T_HIGH: High-confidence objective result "
                        "supports Synthetic A and does not support "
                        "Synthetic B"
                    ),
                    [DIAG_A],
                ),

                outcome(
                    "b",
                    DECISIVE_LOW,
                    DECISIVE_HIGH,
                    "objective_findings",
                    (
                        "T_HIGH: High-confidence objective result "
                        "supports Synthetic B and does not support "
                        "Synthetic A"
                    ),
                    [DIAG_B],
                ),
            ],
        )
    )

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # v3와 달리 global retrieve_memory action을 넣지 않는다.
    #
    # 이유:
    # baseline/routing/voi case의 noise memory가
    # categorical memory outcome model 밖에 존재하여
    # unsupported-observation fallback을 일으키는 것을 방지.
    #
    # B0-B3에서는 memory retrieval 자체가 runner에서 수행된다.
    # Memory-specific B4는 아래 설명처럼 별도 현재 evidence +
    # 이미 retrieval된 semantic memory를 사용할 수 있다.
    # --------------------------------------------------------

    return {
        "schema_version": 1,

        "model_id": (
            "synthetic-v4-process-discriminative"
        ),

        "revision": "v4",

        "provenance": {
            "synthetic": True,

            "review_status": "unreviewed",

            "training_patients": [
                "voi-v4-train-001",
                "voi-v4-train-002",
            ],

            "assumptions": [
                (
                    "Synthetic finite diagnosis universe"
                ),
                (
                    "Categorical outcome likelihood model"
                ),
                (
                    "Objective evidence is required "
                    "for supported finalization"
                ),
                (
                    "Synthetic action costs are utility units "
                    "rather than clinical monetary costs"
                ),
            ],
        },

        "diagnoses": {
            DIAG_A: "general_medicine",
            DIAG_B: "general_medicine",
        },

        "prior": {
            DIAG_A: 0.5,
            DIAG_B: 0.5,
        },

        "terminal_utility": {
            DIAG_A: {
                DIAG_A: 1,
                DIAG_B: 0,
            },

            DIAG_B: {
                DIAG_A: 0,
                DIAG_B: 1,
            },
        },

        "cost_weights": {
            "money": 1,
            "minutes": 0,
            "tokens": 0,
        },

        "stop_probability": (
            STOP_PROBABILITY
        ),

        "horizon": 2,

        "actions": actions,
    }


# ============================================================
# Likelihood safety validation
# ============================================================

def posterior_probability(
    prior,
    p_supported,
    p_other,
):
    numerator = (
        prior
        * p_supported
    )

    denominator = (
        numerator
        + (1 - prior)
        * p_other
    )

    return (
        numerator
        / denominator
    )


def validate_decisive_outcomes(
    model,
):
    """
    v2의 0.90 vs threshold 0.95 문제를
    generator 단계에서 차단한다.

    단일 diagnosis를 지원하는 objective outcome은
    conservative prior=0.10에서도 threshold를 넘어야 한다.
    """

    threshold = (
        model["stop_probability"]
    )

    conservative_prior = 0.10

    checked = 0

    for action in model["actions"]:

        if action["type"] != "request_test":
            continue

        for row in action["outcomes"]:

            supports = (
                row["supports_diagnoses"]
            )

            if len(supports) != 1:
                continue

            diagnosis = supports[0]

            other = (
                DIAG_B
                if diagnosis == DIAG_A
                else DIAG_A
            )

            posterior = posterior_probability(
                conservative_prior,
                row["likelihood"][diagnosis],
                row["likelihood"][other],
            )

            if posterior < threshold:

                raise ValueError(
                    "Unsafe decisive likelihood: "
                    f"{action['id']} / "
                    f"{row['id']} -> "
                    f"{posterior:.6f} "
                    f"< stop_probability "
                    f"{threshold:.6f}"
                )

            checked += 1

    if checked == 0:
        raise ValueError(
            "No decisive outcomes checked."
        )

    print(
        "VoI likelihood safety check passed:",
        checked,
        "decisive outcomes;"
        " threshold =",
        threshold,
    )


# ============================================================
# Dataset
# ============================================================

def build_dataset():

    cases = []

    labels = {}

    annotations = {}

    memory = []

    scenarios = []

    groups = [
        "baseline",
        "memory_critical",
        "routing_critical",
        "voi_critical",
    ]

    number = 1

    for group in groups:

        for index in range(
            N_PER_GROUP
        ):

            patient_id = (
                f"challenge-v4-test-p"
                f"{number:03d}"
            )

            diagnosis = (
                DIAG_A
                if index % 2 == 0
                else DIAG_B
            )

            if group == "baseline":

                case = build_baseline_case(
                    patient_id,
                    diagnosis,
                )

            elif group == "memory_critical":

                case = build_memory_case(
                    patient_id,
                    diagnosis,
                )

            elif group == "routing_critical":

                case = build_routing_case(
                    patient_id,
                    diagnosis,
                )

            else:

                case = build_voi_case(
                    patient_id,
                    diagnosis,
                )

            cases.append(case)

            key = visit_key(
                patient_id,
                "v1",
            )

            labels[key] = diagnosis

            relevant_ids = []

            # =================================================
            # Relevant longitudinal record
            # =================================================

            if group == "memory_critical":

                relevant_id = (
                    f"{patient_id}-relevant"
                )

                text = (
                    "Previous documented episode was classified "
                    "as longitudinal pattern alpha, which corresponds "
                    "to Synthetic A."
                    if diagnosis == DIAG_A
                    else
                    "Previous documented episode was classified "
                    "as longitudinal pattern beta, which corresponds "
                    "to Synthetic B."
                )

                memory.append(
                    memory_record(
                        relevant_id,
                        patient_id,
                        text,
                    )
                )

                relevant_ids.append(
                    relevant_id
                )

            # =================================================
            # Distractors
            # =================================================

            distractors = [
                (
                    "Remote ankle injury resolved "
                    "without residual symptoms."
                ),

                (
                    "Routine dental visit completed "
                    "without complication."
                ),

                (
                    "Administrative travel documentation "
                    "was reviewed."
                ),
            ]

            for distractor_index, text in enumerate(
                distractors
            ):

                memory.append(
                    memory_record(
                        (
                            f"{patient_id}-"
                            f"noise-{distractor_index}"
                        ),
                        patient_id,
                        text,
                    )
                )

            # =================================================
            # Future leakage sentinel
            # =================================================

            future = memory_record(
                f"{patient_id}-future",
                patient_id,
                (
                    "Future sentinel information must "
                    "never be visible at v1."
                ),
                visit_id="v2",
                started_at=(
                    "2027-01-01T00:00:00Z"
                ),
                available_at=(
                    "2027-01-01T00:00:00Z"
                ),
            )

            memory.append(future)

            annotations[key] = {
                "relevant_memory_ids": (
                    relevant_ids
                ),

                "stale_memory_ids": [],
            }

            scenarios.append(
                {
                    "patient_id": patient_id,
                    "visit_id": "v1",
                    "split": "test",
                    "group": group,
                }
            )

            number += 1

    return (
        cases,
        labels,
        annotations,
        memory,
        scenarios,
    )


# ============================================================
# Prices
# ============================================================

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


# ============================================================
# Plan
# ============================================================

def build_plan():
    return {
        "schema_version": 1,

        "provenance": {
            "synthetic": True,

            "review_status": (
                "unreviewed"
            ),

            "scope": (
                "frozen process-discriminative "
                "synthetic challenge; "
                "not clinical evidence"
            ),

            "split": "test_v4",

            "routing": (
                "synthetic pre-specified routing "
                "utility; evaluation patients excluded "
                "from fitting"
            ),
        },

        "repeats": 1,

        "retrieved_mode": (
            "selective"
        ),

        "top_k": 1,

        "minute_limit": 30,

        "inputs": {
            "cases": (
                "cases_test.json"
            ),

            "labels": (
                "labels_test.json"
            ),

            "memory": (
                "memory.json"
            ),

            "annotations": (
                "annotations_test.json"
            ),

            "registry": (
                "registry.json"
            ),

            "routing_utility": (
                "routing_utility.json"
            ),

            "prices": (
                "prices.json"
            ),

            "voi_model": (
                "model.json"
            ),

            "scenarios": (
                "scenarios.json"
            ),
        },
    }


# ============================================================
# Main
# ============================================================

def main():

    (
        cases,
        labels,
        annotations,
        memory,
        scenarios,
    ) = build_dataset()

    registry = (
        build_registry()
    )

    routing_utility = (
        build_routing_utility(
            registry
        )
    )

    voi_model = (
        build_voi_model()
    )

    # IMPORTANT:
    # 결과를 쓰기 전 종료 가능성 확인.
    validate_decisive_outcomes(
        voi_model
    )

    assert len(cases) == 40
    assert len(labels) == 40
    assert len(annotations) == 40
    assert len(scenarios) == 40

    assert (
        len({
            row["case_id"]
            for row in cases
        })
        == 40
    )

    write_json(
        "cases_test.json",
        cases,
    )

    write_json(
        "labels_test.json",
        labels,
    )

    write_json(
        "annotations_test.json",
        annotations,
    )

    write_json(
        "memory.json",
        {
            "schema_version": 1,
            "records": memory,
        },
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
        voi_model,
    )

    write_json(
        "prices.json",
        build_prices(),
    )

    write_json(
        "plan_test.json",
        build_plan(),
    )

    (
        ROOT / "README.md"
    ).write_text(
        """# Challenge v4

Frozen synthetic process-discriminative challenge.

Evaluation set:
- 40 patients
- 40 independent visits
- 10 baseline
- 10 memory-critical
- 10 routing-critical
- 10 VoI-critical

Key design:
- baseline has explicit decisive objective evidence
- memory-critical needs current objective evidence plus longitudinal context
- routing-critical requires specialty-gated objective testing
- VoI-critical contrasts low-information and high-information tests
- global modeled memory action is excluded to avoid unsupported categorical memory observations
- decisive likelihoods are checked against the stopping threshold before generation

Synthetic and not clinically reviewed.
The test set must not be tuned after viewing final experimental results.
""",
        encoding="utf-8",
    )

    print()
    print(
        "========================================"
    )
    print(
        "Challenge v4 generated"
    )
    print(
        "========================================"
    )

    print(
        "Patients:",
        40,
    )

    print(
        "Visits:",
        len(cases),
    )

    print(
        "Groups:",
        "4 x 10",
    )

    print(
        "Stop probability:",
        STOP_PROBABILITY,
    )

    print(
        "IMPORTANT: freeze v4 before final evaluation."
    )


if __name__ == "__main__":
    main()