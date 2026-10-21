import json
import math
from pathlib import Path


ROOT = Path("app/data/challenge_v3")

N_PER_GROUP = 10

DIAG_A = "Synthetic A"
DIAG_B = "Synthetic B"

STOP_PROBABILITY = 0.95

# Decisive evidence는 매우 강하게 설정한다.
# v2의 0.90 < 0.95 문제를 방지하기 위함.
DECISIVE_HIGH = 0.999
DECISIVE_LOW = 0.001


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

    print("written:", path)


def visit_key(patient_id, visit_id):
    # 기존 프로젝트의 visit_key와 동일한 직렬화 형식
    return json.dumps(
        [patient_id, visit_id],
        ensure_ascii=False,
    )


def memory_record(
    memory_id,
    patient_id,
    text,
    *,
    date="2026-01-01T00:00:00Z",
):
    return {
        "memory_id": memory_id,
        "patient_id": patient_id,
        "visit_id": "v0",
        "visit_started_at": date,
        "observed_at": date,
        "available_at": date,
        "source_id": "synthetic-challenge-v3",
        "kind": "history",
        "text": text,
        "supersedes": [],
    }


def test_entry(result):
    return {
        "result": result,
    }


def base_resources(test_names):
    return {
        "test_resources": {
            name: "lab_slot"
            for name in test_names
        },
        "test_occupancy": {
            name: 1
            for name in test_names
        },
        "test_turnaround": {
            name: 1
            for name in test_names
        },
    }


# ============================================================
# Cases
# ============================================================

def build_baseline_case(patient_id, diagnosis):
    """
    B0도 풀 수 있어야 하는 일반적인 easy control.

    T_BASE 하나가 강한 객관적 evidence.
    """

    result = (
        "Baseline alpha signal"
        if diagnosis == DIAG_A
        else "Baseline beta signal"
    )

    tests = ["T_BASE"]

    return {
        "case_id": f"{patient_id}-v1",
        "longitudinal": {
            "patient_id": patient_id,
            "visit_id": "v1",
            "started_at": "2026-03-01T00:00:00Z",
        },
        "doctor_visible_info": {
            "chief_complaint": "General synthetic diagnostic concern",
            "initial_vitals": {
                "spo2": 98,
            },
        },
        "patient_visible_info": {
            "history": "Symptoms started recently.",
        },
        "available_tests": tests,
        "test_access": {
            "T_BASE": [
                "er",
                "neurology",
                "pulmonology",
            ],
        },
        "hidden_test_results": {
            "T_BASE": test_entry(result),
        },
        "resource_profile": base_resources(tests),
    }


def build_memory_case(patient_id, diagnosis):
    """
    현재 정보 + 객관적 검사만으로 A/B 구분이 어렵다.

    T_CONTEXT는 두 진단 모두에서 동일한 결과를 보인다.
    과거 longitudinal memory가 A/B를 구별한다.

    따라서:
      B0 < B1/B2 를 기대할 수 있다.
    """

    tests = ["T_CONTEXT"]

    return {
        "case_id": f"{patient_id}-v1",
        "longitudinal": {
            "patient_id": patient_id,
            "visit_id": "v1",
            "started_at": "2026-03-01T00:00:00Z",
        },
        "doctor_visible_info": {
            "chief_complaint": (
                "Recurrent longitudinal pattern concern "
                "with nonspecific current symptoms"
            ),
            "initial_vitals": {
                "spo2": 98,
            },
        },
        "patient_visible_info": {
            "history": (
                "The current episode resembles a previous event, "
                "but the patient cannot recall the distinguishing detail."
            ),
        },
        "available_tests": tests,
        "test_access": {
            "T_CONTEXT": [
                "er",
                "neurology",
                "pulmonology",
            ],
        },
        "hidden_test_results": {
            # A/B 모두 같은 result.
            # 현재 visit alone으로는 정답 노출 안 함.
            "T_CONTEXT": test_entry(
                "Shared objective marker present"
            ),
        },
        "resource_profile": base_resources(tests),
    }


def build_routing_case(patient_id, diagnosis):
    """
    ER은 generic screen만 볼 수 있다.

    A라면 neurology-specific test가 결정적이고,
    B라면 pulmonology-specific test가 결정적이다.

    ER은 T_NEURO/T_PULM에 접근할 수 없다.

    따라서 Routing이 실제 정보 접근 차이를 만든다.
    """

    if diagnosis == DIAG_A:
        complaint = (
            "Recurrent focal pathway concern with intermittent "
            "sensory-pattern symptoms"
        )

        neuro = "Neuro-specific alpha signal detected"
        pulm = "Pulmonary study nondiagnostic"

    else:
        complaint = (
            "Recurrent respiratory pathway concern with intermittent "
            "breathing-pattern symptoms"
        )

        neuro = "Neurologic study nondiagnostic"
        pulm = "Pulmonary-specific beta signal detected"

    tests = [
        "T_SCREEN",
        "T_NEURO",
        "T_PULM",
    ]

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
                "spo2": 97,
            },
        },
        "patient_visible_info": {
            "history": (
                "The current symptoms remain diagnostically ambiguous."
            ),
        },
        "available_tests": tests,

        # 핵심.
        "test_access": {
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

        "hidden_test_results": {
            "T_SCREEN": test_entry(
                "Shared routing screen positive"
            ),
            "T_NEURO": test_entry(neuro),
            "T_PULM": test_entry(pulm),
        },

        "resource_profile": base_resources(tests),
    }


def build_voi_case(patient_id, diagnosis):
    """
    ER이 선택할 수 있는 검사 2개.

    T_LOW:
      cheap하지만 정보량이 낮음.

    T_HIGH:
      비용은 더 높지만 거의 결정적.

    VoI가 정확도보다는 action efficiency를 보여주도록 함.
    """

    if diagnosis == DIAG_A:
        low = "Weak alpha tendency"
        high = "High-confidence alpha signal"
    else:
        low = "Weak beta tendency"
        high = "High-confidence beta signal"

    tests = [
        "T_LOW",
        "T_HIGH",
    ]

    return {
        "case_id": f"{patient_id}-v1",
        "longitudinal": {
            "patient_id": patient_id,
            "visit_id": "v1",
            "started_at": "2026-03-01T00:00:00Z",
        },
        "doctor_visible_info": {
            "chief_complaint": (
                "Synthetic complaint requiring selective "
                "information acquisition"
            ),
            "initial_vitals": {
                "spo2": 98,
            },
        },
        "patient_visible_info": {
            "history": (
                "Initial history does not distinguish the candidate diagnoses."
            ),
        },
        "available_tests": tests,
        "test_access": {
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
        "hidden_test_results": {
            "T_LOW": test_entry(low),
            "T_HIGH": test_entry(high),
        },
        "resource_profile": base_resources(tests),
    }


# ============================================================
# Registry / Routing
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
                "version": "challenge-v3-er",
                "keywords": [],
            },
            {
                "agent_id": "local-neurology",
                "role": "specialty",
                "department": "neurology",
                "model": "qwen-neurology:latest",
                "version": "challenge-v3-neuro",
                "keywords": [
                    "focal",
                    "sensory",
                    "neurologic",
                    "neurology",
                ],
            },
            {
                "agent_id": "local-pulmonology",
                "role": "specialty",
                "department": "pulmonology",
                "model": "qwen-pulmonology:latest",
                "version": "challenge-v3-pulm",
                "keywords": [
                    "respiratory",
                    "breathing",
                    "pulmonary",
                    "pulmonology",
                ],
            },
        ],
    }


def build_routing_utility(registry):
    """
    같은 observation에서 모든 specialty를 비교하도록 구성.
    기존 RoutingUtility validator 조건을 만족한다.
    """

    neuro_obs_1 = [
        "recurrent",
        "focal",
        "pathway",
        "sensory",
        "pattern",
    ]

    neuro_obs_2 = [
        "focal",
        "neurologic",
        "sensory",
        "concern",
    ]

    pulm_obs_1 = [
        "recurrent",
        "respiratory",
        "pathway",
        "breathing",
        "pattern",
    ]

    pulm_obs_2 = [
        "pulmonary",
        "respiratory",
        "breathing",
        "concern",
    ]

    samples = []

    training = [
        (
            "router-train-neuro-1",
            neuro_obs_1,
            True,
            False,
        ),
        (
            "router-train-neuro-2",
            neuro_obs_2,
            True,
            False,
        ),
        (
            "router-train-pulm-1",
            pulm_obs_1,
            False,
            True,
        ),
        (
            "router-train-pulm-2",
            pulm_obs_2,
            False,
            True,
        ),
    ]

    for patient_id, tokens, neuro_correct, pulm_correct in training:

        decision_id = f"{patient_id}-probe"

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
# VoI model
# ============================================================

def outcome(
    outcome_id,
    a_probability,
    b_probability,
    source,
    text,
    supports=None,
):
    return {
        "id": outcome_id,
        "likelihood": {
            DIAG_A: a_probability,
            DIAG_B: b_probability,
        },
        "observation": {
            "source": source,
            "text": text,
        },
        "supports_diagnoses": supports or [],
    }


def test_action(
    action_id,
    target,
    cost,
    first,
    second,
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
        "outcomes": [
            first,
            second,
        ],
    }


def build_voi_model():

    actions = []

    # ---------------------------------------------------------
    # BASELINE decisive test
    # ---------------------------------------------------------

    actions.append(
        test_action(
            "baseline-test",
            "T_BASE",
            0.05,
            outcome(
                "alpha",
                DECISIVE_HIGH,
                DECISIVE_LOW,
                "objective_findings",
                "T_BASE: Baseline alpha signal",
                [DIAG_A],
            ),
            outcome(
                "beta",
                DECISIVE_LOW,
                DECISIVE_HIGH,
                "objective_findings",
                "T_BASE: Baseline beta signal",
                [DIAG_B],
            ),
        )
    )

    # ---------------------------------------------------------
    # MEMORY CASE OBJECTIVE CONTEXT
    #
    # objective evidence 자체는 A/B를 구분하지 않지만
    # 두 진단 모두의 finalization 근거로 사용할 수 있다.
    # ---------------------------------------------------------

    actions.append(
        test_action(
            "context-test",
            "T_CONTEXT",
            0.01,
            outcome(
                "present",
                0.5,
                0.5,
                "objective_findings",
                "T_CONTEXT: Shared objective marker present",
                [DIAG_A, DIAG_B],
            ),
            outcome(
                "absent",
                0.5,
                0.5,
                "objective_findings",
                "T_CONTEXT: Shared objective marker absent",
                [DIAG_A, DIAG_B],
            ),
        )
    )

    # ---------------------------------------------------------
    # ROUTING generic screen
    # ---------------------------------------------------------

    actions.append(
        test_action(
            "routing-screen",
            "T_SCREEN",
            0.01,
            outcome(
                "positive",
                0.5,
                0.5,
                "objective_findings",
                "T_SCREEN: Shared routing screen positive",
                [DIAG_A, DIAG_B],
            ),
            outcome(
                "negative",
                0.5,
                0.5,
                "objective_findings",
                "T_SCREEN: Shared routing screen negative",
                [DIAG_A, DIAG_B],
            ),
        )
    )

    # ---------------------------------------------------------
    # NEURO specialty test
    # ---------------------------------------------------------

    actions.append(
        test_action(
            "neuro-test",
            "T_NEURO",
            0.05,
            outcome(
                "alpha",
                DECISIVE_HIGH,
                DECISIVE_LOW,
                "objective_findings",
                "T_NEURO: Neuro-specific alpha signal detected",
                [DIAG_A],
            ),
            outcome(
                "nondiagnostic",
                DECISIVE_LOW,
                DECISIVE_HIGH,
                "objective_findings",
                "T_NEURO: Neurologic study nondiagnostic",
                [],
            ),
        )
    )

    # ---------------------------------------------------------
    # PULMONOLOGY specialty test
    # ---------------------------------------------------------

    actions.append(
        test_action(
            "pulm-test",
            "T_PULM",
            0.05,
            outcome(
                "nondiagnostic",
                DECISIVE_HIGH,
                DECISIVE_LOW,
                "objective_findings",
                "T_PULM: Pulmonary study nondiagnostic",
                [],
            ),
            outcome(
                "beta",
                DECISIVE_LOW,
                DECISIVE_HIGH,
                "objective_findings",
                "T_PULM: Pulmonary-specific beta signal detected",
                [DIAG_B],
            ),
        )
    )

    # ---------------------------------------------------------
    # LOW-information test
    # ---------------------------------------------------------

    actions.append(
        test_action(
            "low-info-test",
            "T_LOW",
            0.01,
            outcome(
                "alpha",
                0.60,
                0.40,
                "objective_findings",
                "T_LOW: Weak alpha tendency",
                [],
            ),
            outcome(
                "beta",
                0.40,
                0.60,
                "objective_findings",
                "T_LOW: Weak beta tendency",
                [],
            ),
        )
    )

    # ---------------------------------------------------------
    # HIGH-information test
    # ---------------------------------------------------------

    actions.append(
        test_action(
            "high-info-test",
            "T_HIGH",
            0.08,
            outcome(
                "alpha",
                DECISIVE_HIGH,
                DECISIVE_LOW,
                "objective_findings",
                "T_HIGH: High-confidence alpha signal",
                [DIAG_A],
            ),
            outcome(
                "beta",
                DECISIVE_LOW,
                DECISIVE_HIGH,
                "objective_findings",
                "T_HIGH: High-confidence beta signal",
                [DIAG_B],
            ),
        )
    )

    # ---------------------------------------------------------
    # LONGITUDINAL MEMORY
    #
    # 0.97 > stop threshold.
    #
    # 단, memory alone은 objective evidence가 아니므로
    # T_CONTEXT와 함께 있어야 final diagnosis 가능.
    # ---------------------------------------------------------

    actions.append(
        {
            "id": "memory",
            "type": "retrieve_memory",
            "target": "longitudinal",
            "cost": {
                "money": 0.01,
                "minutes": 0,
                "tokens": 0,
            },
            "outcomes": [
                outcome(
                    "alpha",
                    0.97,
                    0.03,
                    "memory",
                    "Longitudinal pattern alpha.",
                ),
                outcome(
                    "beta",
                    0.03,
                    0.97,
                    "memory",
                    "Longitudinal pattern beta.",
                ),
            ],
        }
    )

    return {
        "schema_version": 1,
        "model_id": "synthetic-v3-process-aware",
        "revision": "v3",
        "provenance": {
            "synthetic": True,
            "review_status": "unreviewed",
            "training_patients": [
                "voi-train-001",
                "voi-train-002",
            ],
            "assumptions": [
                "Fixed finite diagnosis universe",
                "Categorical synthetic outcome probabilities",
                "Objective support required for supported diagnosis",
                "Synthetic costs are utility units, not clinical prices",
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

        # 변경하지 말 것.
        "stop_probability": STOP_PROBABILITY,

        "horizon": 2,

        "actions": actions,
    }


# ============================================================
# Safety validation
# ============================================================

def posterior_for_supported(
    prior_supported,
    p_outcome_given_supported,
    p_outcome_given_other,
):
    numerator = (
        prior_supported
        * p_outcome_given_supported
    )

    denominator = numerator + (
        (1 - prior_supported)
        * p_outcome_given_other
    )

    return numerator / denominator


def validate_decisive_likelihoods(model):
    """
    v2에서 발생한
       likelihood 0.90 < stop_probability 0.95
    문제를 생성 시점에 차단한다.

    decisive single-diagnosis objective outcome은
    불리한 prior=0.10에서도 stop threshold를 넘는지 검사.
    """

    threshold = model["stop_probability"]

    conservative_prior = 0.10

    checked = 0

    for action in model["actions"]:

        if action["type"] != "request_test":
            continue

        for row in action["outcomes"]:

            support = row["supports_diagnoses"]

            # 정확히 하나의 diagnosis만 지지하는
            # decisive outcome만 검사
            if len(support) != 1:
                continue

            target = support[0]

            other = (
                DIAG_B
                if target == DIAG_A
                else DIAG_A
            )

            posterior = posterior_for_supported(
                conservative_prior,
                row["likelihood"][target],
                row["likelihood"][other],
            )

            if posterior < threshold:
                raise ValueError(
                    f"Unsafe VoI likelihood: "
                    f"{action['id']} / {row['id']} "
                    f"posterior={posterior:.6f} "
                    f"< stop_probability={threshold:.6f}"
                )

            checked += 1

    if checked == 0:
        raise ValueError(
            "No decisive VoI outcomes were validated."
        )

    print(
        f"VoI safety check passed: "
        f"{checked} decisive outcomes clear "
        f"stop_probability={threshold}"
    )


# ============================================================
# Dataset
# ============================================================

def build_all():
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

    patient_number = 1

    for group in groups:

        for local_index in range(N_PER_GROUP):

            patient_id = (
                f"challenge-v3-test-p"
                f"{patient_number:03d}"
            )

            # group 내 A/B 균형
            diagnosis = (
                DIAG_A
                if local_index % 2 == 0
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

            elif group == "voi_critical":
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

            relevant = []

            # -------------------------------------------------
            # Memory-critical
            # -------------------------------------------------

            if group == "memory_critical":

                relevant_id = (
                    f"{patient_id}-relevant"
                )

                text = (
                    "Longitudinal pattern alpha."
                    if diagnosis == DIAG_A
                    else
                    "Longitudinal pattern beta."
                )

                memory.append(
                    memory_record(
                        relevant_id,
                        patient_id,
                        text,
                    )
                )

                relevant.append(
                    relevant_id
                )

            # -------------------------------------------------
            # Distractor records for EVERY patient
            # -------------------------------------------------

            for n, text in enumerate(
                [
                    "Remote ankle injury resolved.",
                    "Routine dental care completed.",
                    "Administrative travel note reviewed.",
                ]
            ):

                memory.append(
                    memory_record(
                        f"{patient_id}-noise-{n}",
                        patient_id,
                        text,
                    )
                )

            # Future sentinel
            future_id = (
                f"{patient_id}-future"
            )

            future_date = (
                "2027-01-01T00:00:00Z"
            )

            future = memory_record(
                future_id,
                patient_id,
                "Future sentinel must never be visible.",
                date=future_date,
            )

            future["visit_id"] = "v2"

            memory.append(future)

            annotations[key] = {
                "relevant_memory_ids": relevant,
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

            patient_number += 1

    return (
        cases,
        labels,
        annotations,
        memory,
        scenarios,
    )


# ============================================================
# Misc artifacts
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


def build_plan():
    return {
        "schema_version": 1,
        "provenance": {
            "synthetic": True,
            "review_status": "unreviewed",
            "scope": (
                "process-discriminative synthetic challenge; "
                "not clinical evidence"
            ),
            "split": "test_v3",
            "routing": (
                "pre-existing synthetic routing utility; "
                "not fitted on evaluation patients"
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

    (
        cases,
        labels,
        annotations,
        memory,
        scenarios,
    ) = build_all()

    registry = build_registry()

    routing_utility = (
        build_routing_utility(
            registry
        )
    )

    voi_model = build_voi_model()

    # ---------------------------------------------------------
    # 중요:
    # 데이터를 쓰기 전에 likelihood / stop threshold 검증
    # ---------------------------------------------------------

    validate_decisive_likelihoods(
        voi_model
    )

    assert len(cases) == 40
    assert len(labels) == 40
    assert len(annotations) == 40
    assert len(scenarios) == 40

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
        ROOT
        / "README.md"
    ).write_text(
        """# Challenge v3

Synthetic, unreviewed process-discriminative challenge.

40 evaluation patients / 40 visits.

Groups:
- baseline: 10
- memory_critical: 10
- routing_critical: 10
- voi_critical: 10

Design goals:
- remove single-test shortcut from memory/routing cases
- require longitudinal context in memory-critical cases
- restrict specialty-specific tests in routing-critical cases
- provide low/high information actions in VoI-critical cases
- retain easy baseline controls

This dataset is not clinical evidence.
Do not tune against final test outcomes.
""",
        encoding="utf-8",
    )

    print()
    print("================================")
    print("Challenge v3 generated")
    print("================================")
    print("Patients :", 40)
    print("Visits   :", len(cases))
    print("Labels   :", len(labels))
    print("Groups   : 4 x 10")
    print(
        "VoI stop probability:",
        STOP_PROBABILITY,
    )


if __name__ == "__main__":
    main()