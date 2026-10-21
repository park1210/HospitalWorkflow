from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


# ============================================================
# Page
# ============================================================

st.set_page_config(
    page_title="Medical LLM ER Simulation",
    page_icon="🏥",
    layout="wide",
)

st.title("🏥 Medical LLM ER Simulation")
st.caption(
    "Longitudinal Memory · Adaptive Specialty Routing · "
    "Value of Information"
)


# ============================================================
# Helpers
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def existing_default_output() -> Path:
    candidates = [
        PROJECT_ROOT / "outputs" / "paper_test_v4_r1",
        PROJECT_ROOT / "outputs" / "paper_test_v3_r1",
        PROJECT_ROOT / "outputs" / "paper_test_v2_r1",
    ]

    for path in candidates:
        if path.exists():
            return path

    return PROJECT_ROOT / "outputs" / "paper_test_v4_r1"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(
        path,
        encoding="utf-8-sig",
    )


def value_or_dash(value, digits=3):
    if value is None:
        return "-"

    try:
        if pd.isna(value):
            return "-"
    except Exception:
        pass

    if isinstance(value, float):
        return f"{value:.{digits}f}"

    return str(value)


def safe_list(value):
    return value if isinstance(value, list) else []


def safe_dict(value):
    return value if isinstance(value, dict) else {}


def condition_description(condition: str) -> str:
    mapping = {
        "B0": "No Memory + ER only",
        "B1": "Full History + ER only",
        "B2": "Retrieved Memory + ER only",
        "B3": "Retrieved Memory + Adaptive Routing",
        "B4": "Retrieved Memory + Adaptive Routing + VoI",
        "R0": "Retrieved Memory + LLM Routing",
    }

    return mapping.get(
        condition,
        condition,
    )


def locate_report(
    output_dir: Path,
    condition: str,
    repeat: int,
) -> Path | None:
    # episodes.csv repeat is zero-based.
    path = output_dir / (
        f"{condition}_r{repeat + 1:02d}.report.json"
    )

    if path.exists():
        return path

    return None


def find_visit(
    report: dict,
    patient_id: str,
    visit_id: str,
):
    for visit in report.get("visits", []):
        identity = safe_dict(
            visit.get("identity")
        )

        if (
            identity.get("patient_id") == patient_id
            and identity.get("visit_id") == visit_id
        ):
            return visit

    return None


def visit_runtime(visit: dict | None):
    if not visit:
        return {}

    state = safe_dict(
        visit.get("final_state")
    )

    cases = safe_dict(
        state.get("cases")
    )

    if not cases:
        return {}

    return next(
        iter(cases.values())
    )


def final_diagnosis(runtime: dict):
    return (
        runtime.get("assessment_summary")
        or runtime.get("final_diagnosis")
        or "Not available"
    )


def build_trace(runtime: dict) -> pd.DataFrame:
    rows = []

    # --------------------------------------------------------
    # LLM / decision audit
    # --------------------------------------------------------

    for index, audit in enumerate(
        safe_list(runtime.get("llm_audit"))
    ):
        if audit.get("status") != "success":
            continue

        decision = safe_dict(
            audit.get("decision")
        )

        role = audit.get(
            "role",
            "unknown",
        )

        routing = safe_dict(
            audit.get("routing")
        )

        target = decision.get(
            "target",
            "",
        )

        action = decision.get(
            "action",
            "",
        )

        routed = ", ".join(
            routing.get(
                "allowed_departments",
                [],
            )
        )

        rows.append(
            {
                "Order": index + 1,
                "Source": "LLM",
                "Role": role,
                "Action": action,
                "Target": target,
                "Routed Specialty": routed,
                "Rationale": decision.get(
                    "rationale",
                    "",
                ),
            }
        )

    # --------------------------------------------------------
    # VoI decisions
    # --------------------------------------------------------

    voi_state = safe_dict(
        runtime.get("voi_state")
    )

    history = safe_list(
        voi_state.get("history")
    )

    base_order = len(rows)

    for index, trace in enumerate(history):
        if trace.get("status") != "selected":
            continue

        rows.append(
            {
                "Order": base_order + index + 1,
                "Source": "VoI",
                "Role": "ER",
                "Action": trace.get(
                    "selected_action",
                    "",
                ),
                "Target": trace.get(
                    "target",
                    "",
                ),
                "Routed Specialty": "",
                "Rationale": trace.get(
                    "rationale",
                    "",
                ),
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "Order",
                "Source",
                "Role",
                "Action",
                "Target",
                "Routed Specialty",
                "Rationale",
            ]
        )

    result = pd.DataFrame(rows)

    return result.sort_values(
        "Order"
    ).reset_index(drop=True)


def collect_routing(runtime: dict) -> pd.DataFrame:
    rows = []

    for index, audit in enumerate(
        safe_list(runtime.get("llm_audit"))
    ):
        routing = safe_dict(
            audit.get("routing")
        )

        if not routing:
            continue

        estimates = safe_dict(
            routing.get("utility_estimates")
        )

        allowed = routing.get(
            "allowed_departments",
            [],
        )

        candidates = routing.get(
            "candidate_departments",
            [],
        )

        if estimates:
            for department, estimate in estimates.items():
                estimate = safe_dict(
                    estimate
                )

                rows.append(
                    {
                        "Decision": index + 1,
                        "Mode": routing.get(
                            "mode",
                            "",
                        ),
                        "Department": department,
                        "Selected": (
                            department in allowed
                        ),
                        "Utility": estimate.get(
                            "utility"
                        ),
                        "Estimated Accuracy": estimate.get(
                            "accuracy"
                        ),
                        "Cost": estimate.get(
                            "cost"
                        ),
                        "Latency": estimate.get(
                            "latency_seconds"
                        ),
                    }
                )

        else:
            for department in candidates:
                rows.append(
                    {
                        "Decision": index + 1,
                        "Mode": routing.get(
                            "mode",
                            "",
                        ),
                        "Department": department,
                        "Selected": (
                            department in allowed
                        ),
                        "Utility": None,
                        "Estimated Accuracy": None,
                        "Cost": None,
                        "Latency": None,
                    }
                )

    return pd.DataFrame(rows)


def collect_voi(runtime: dict) -> pd.DataFrame:
    rows = []

    state = safe_dict(
        runtime.get("voi_state")
    )

    for decision_index, trace in enumerate(
        safe_list(state.get("history"))
    ):
        candidates = safe_list(
            trace.get("candidates")
        )

        for candidate in candidates:
            rows.append(
                {
                    "Decision": decision_index + 1,
                    "Action ID": candidate.get(
                        "action_id"
                    ),
                    "VoI": candidate.get(
                        "voi"
                    ),
                    "Information Gain": candidate.get(
                        "information_gain_nats"
                    ),
                    "Cost Penalty": candidate.get(
                        "cost_penalty"
                    ),
                    "Selected": (
                        candidate.get("action_id")
                        == trace.get("action_id")
                    ),
                }
            )

    return pd.DataFrame(rows)


def collect_memory(
    visit: dict | None,
) -> pd.DataFrame:
    if not visit:
        return pd.DataFrame()

    context = safe_dict(
        visit.get("memory_context")
    )

    records = safe_list(
        context.get("records")
    )

    eligible = set(
        safe_list(
            visit.get(
                "eligible_memory_ids"
            )
        )
    )

    rows = []

    for record in records:
        memory_id = record.get(
            "memory_id",
            "",
        )

        rows.append(
            {
                "Memory ID": memory_id,
                "Relevant / Eligible": (
                    memory_id in eligible
                ),
                "Status": record.get(
                    "status_as_of_visit",
                    "",
                ),
                "Kind": record.get(
                    "kind",
                    "",
                ),
                "Text": record.get(
                    "text",
                    "",
                ),
            }
        )

    return pd.DataFrame(rows)


def selected_voi_belief(runtime: dict):
    state = safe_dict(
        runtime.get("voi_state")
    )

    return safe_dict(
        state.get("belief")
    )


# ============================================================
# Sidebar / data loading
# ============================================================

default_output = existing_default_output()

with st.sidebar:
    st.header("Experiment")

    output_text = st.text_input(
        "Output directory",
        value=str(default_output),
    )

    output_dir = Path(
        output_text
    )

    st.caption(
        "Example: outputs/paper_test_v4_r1"
    )


if not output_dir.is_absolute():
    output_dir = (
        PROJECT_ROOT / output_dir
    ).resolve()


required_files = {
    "episodes": output_dir / "episodes.csv",
    "table": output_dir / "table.csv",
    "stratified": output_dir / "stratified_table.csv",
    "results": output_dir / "results.json",
}


missing = [
    name
    for name, path in required_files.items()
    if not path.exists()
]


if missing:
    st.warning(
        "Experiment output is not ready yet.\n\n"
        f"Missing: {', '.join(missing)}"
    )

    st.code(
        "python -m app.scripts.run_paper_experiments `\n"
        "  --plan outputs/memory_v4_test/plan_semantic.json `\n"
        "  --execute `\n"
        "  --conditions B0 B1 B2 B3 B4 `\n"
        "  --repeats 1 `\n"
        "  --output-dir outputs/paper_test_v4_r1"
    )

    st.stop()


episodes = read_csv(
    required_files["episodes"]
)

table = read_csv(
    required_files["table"]
)

stratified = read_csv(
    required_files["stratified"]
)

results = read_json(
    required_files["results"]
)


# ============================================================
# Sidebar selectors
# ============================================================

with st.sidebar:
    conditions = sorted(
        episodes["condition"]
        .dropna()
        .unique()
        .tolist()
    )

    selected_condition = st.selectbox(
        "Condition",
        conditions,
        index=(
            conditions.index("B4")
            if "B4" in conditions
            else 0
        ),
        format_func=lambda x: (
            f"{x} · "
            f"{condition_description(x)}"
        ),
    )

    filtered = episodes[
        episodes["condition"]
        == selected_condition
    ]

    patient_ids = sorted(
        filtered["patient_id"]
        .astype(str)
        .unique()
        .tolist()
    )

    selected_patient = st.selectbox(
        "Patient",
        patient_ids,
    )

    patient_rows = filtered[
        filtered["patient_id"]
        .astype(str)
        == selected_patient
    ]

    visit_ids = sorted(
        patient_rows["visit_id"]
        .astype(str)
        .unique()
        .tolist()
    )

    selected_visit = st.selectbox(
        "Visit",
        visit_ids,
    )

    selected_rows = patient_rows[
        patient_rows["visit_id"]
        .astype(str)
        == selected_visit
    ]

    repeats = sorted(
        selected_rows["repeat"]
        .astype(int)
        .unique()
        .tolist()
    )

    selected_repeat = st.selectbox(
        "Repeat",
        repeats,
        format_func=lambda x: (
            f"Run {x + 1}"
        ),
    )


selected_episode = selected_rows[
    selected_rows["repeat"].astype(int)
    == selected_repeat
].iloc[0]


report_path = locate_report(
    output_dir,
    selected_condition,
    selected_repeat,
)

report = (
    read_json(report_path)
    if report_path
    else {}
)

visit = find_visit(
    report,
    selected_patient,
    selected_visit,
)

runtime = visit_runtime(
    visit
)


# ============================================================
# Top summary
# ============================================================

summary_row = table[
    table["condition"]
    == selected_condition
]

if not summary_row.empty:
    summary_row = (
        summary_row.iloc[0]
    )

    col1, col2, col3, col4 = (
        st.columns(4)
    )

    col1.metric(
        "Diagnosis Accuracy",
        value_or_dash(
            summary_row.get(
                "correct_all_planned"
            )
        ),
    )

    col2.metric(
        "Completion",
        value_or_dash(
            summary_row.get(
                "completed"
            )
        ),
    )

    col3.metric(
        "Avg. Actions",
        value_or_dash(
            summary_row.get(
                "actions"
            )
        ),
    )

    col4.metric(
        "Avg. LLM Calls",
        value_or_dash(
            summary_row.get(
                "llm_calls"
            )
        ),
    )


st.divider()


# ============================================================
# Tabs
# ============================================================

tab_overview, tab_patient, tab_memory, tab_voi = st.tabs(
    [
        "📊 Overview",
        "🧑‍⚕️ Patient Trace",
        "🧠 Memory & Routing",
        "🔎 VoI",
    ]
)


# ============================================================
# Overview
# ============================================================

with tab_overview:
    st.subheader(
        "B0–B4 Comparison"
    )

    display_columns = [
        "condition",
        "completed",
        "correct_all_planned",
        "actions",
        "tests",
        "consults",
        "questions",
        "llm_calls",
    ]

    display_columns = [
        column
        for column in display_columns
        if column in table.columns
    ]

    overview_table = table[
        display_columns
    ].copy()

    overview_table = (
        overview_table.rename(
            columns={
                "condition": "Condition",
                "completed": "Completion",
                "correct_all_planned": (
                    "Accuracy"
                ),
                "actions": "Actions",
                "tests": "Tests",
                "consults": "Consults",
                "questions": "Questions",
                "llm_calls": "LLM Calls",
            }
        )
    )

    st.dataframe(
        overview_table,
        use_container_width=True,
        hide_index=True,
    )

    left, right = st.columns(2)

    with left:
        st.markdown(
            "#### Diagnosis Accuracy"
        )

        accuracy_chart = (
            table[
                [
                    "condition",
                    "correct_all_planned",
                ]
            ]
            .set_index("condition")
        )

        st.bar_chart(
            accuracy_chart
        )

    with right:
        st.markdown(
            "#### LLM Calls"
        )

        calls_chart = (
            table[
                [
                    "condition",
                    "llm_calls",
                ]
            ]
            .set_index("condition")
        )

        st.bar_chart(
            calls_chart
        )

    st.markdown(
        "### Scenario-specific Results"
    )

    scenario_metrics = [
        "scenario_group",
        "condition",
        "correct_all_planned",
        "actions",
        "consults",
        "llm_calls",
    ]

    scenario_metrics = [
        column
        for column in scenario_metrics
        if column in stratified.columns
    ]

    scenario_table = stratified[
        scenario_metrics
    ].copy()

    scenario_table = scenario_table.rename(
        columns={
            "scenario_group": "Scenario",
            "condition": "Condition",
            "correct_all_planned": (
                "Accuracy"
            ),
            "actions": "Actions",
            "consults": "Consults",
            "llm_calls": "LLM Calls",
        }
    )

    st.dataframe(
        scenario_table,
        use_container_width=True,
        hide_index=True,
    )

    if {
        "scenario_group",
        "condition",
        "correct_all_planned",
    } <= set(stratified.columns):

        pivot = (
            stratified.pivot(
                index="scenario_group",
                columns="condition",
                values="correct_all_planned",
            )
        )

        st.markdown(
            "#### Accuracy by Scenario"
        )

        st.bar_chart(
            pivot
        )


# ============================================================
# Patient trace
# ============================================================

with tab_patient:
    st.subheader(
        f"{selected_patient} · {selected_visit}"
    )

    col1, col2, col3, col4 = (
        st.columns(4)
    )

    col1.metric(
        "Condition",
        selected_condition,
    )

    col2.metric(
        "Completed",
        (
            "Yes"
            if int(
                selected_episode[
                    "completed"
                ]
            )
            else "No"
        ),
    )

    col3.metric(
        "Correct",
        (
            "Yes"
            if int(
                selected_episode[
                    "correct_all_planned"
                ]
            )
            else "No"
        ),
    )

    col4.metric(
        "Final Diagnosis",
        final_diagnosis(
            runtime
        ),
    )

    if not runtime:
        st.warning(
            "Detailed report for this visit "
            "could not be found."
        )

    else:
        st.markdown(
            "### Clinical State"
        )

        left, right = st.columns(2)

        with left:
            st.write(
                "**Target Department**"
            )

            st.write(
                runtime.get(
                    "target_department",
                    "-",
                )
            )

            st.write(
                "**Completed Tests**"
            )

            tests = safe_list(
                runtime.get(
                    "completed_tests"
                )
            )

            if tests:
                for test in tests:
                    st.write(
                        f"- {test}"
                    )
            else:
                st.write("-")

        with right:
            st.write(
                "**Questions**"
            )

            questions = safe_list(
                runtime.get(
                    "question_history"
                )
            )

            if questions:
                for question in questions:
                    st.write(
                        "- "
                        + str(
                            question.get(
                                "question",
                                "",
                            )
                        )
                    )
            else:
                st.write("-")

            st.write(
                "**Consultations**"
            )

            consults = safe_list(
                runtime.get(
                    "consult_history"
                )
            )

            if consults:
                for consult in consults:
                    st.write(
                        "- "
                        + str(
                            consult.get(
                                "department",
                                "",
                            )
                        )
                    )
            else:
                st.write("-")

        st.markdown(
            "### Decision Trace"
        )

        trace = build_trace(
            runtime
        )

        if trace.empty:
            st.info(
                "No decision trace recorded."
            )
        else:
            st.dataframe(
                trace,
                use_container_width=True,
                hide_index=True,
            )


# ============================================================
# Memory & Routing
# ============================================================

with tab_memory:
    memory_left, routing_right = (
        st.columns(2)
    )

    with memory_left:
        st.subheader(
            "Longitudinal Memory"
        )

        memory_df = collect_memory(
            visit
        )

        if memory_df.empty:
            st.info(
                "No retrieved memory "
                "for this visit."
            )
        else:
            st.dataframe(
                memory_df,
                use_container_width=True,
                hide_index=True,
            )

        if visit:
            evaluation = safe_dict(
                visit.get(
                    "memory_evaluation"
                )
            )

            precision = safe_dict(
                evaluation.get(
                    "precision"
                )
            ).get("value")

            recall = safe_dict(
                evaluation.get(
                    "recall"
                )
            ).get("value")

            p_col, r_col = (
                st.columns(2)
            )

            p_col.metric(
                "Memory Precision",
                value_or_dash(
                    precision
                ),
            )

            r_col.metric(
                "Memory Recall",
                value_or_dash(
                    recall
                ),
            )

    with routing_right:
        st.subheader(
            "Adaptive Routing"
        )

        routing_df = (
            collect_routing(
                runtime
            )
        )

        if routing_df.empty:
            st.info(
                "No routing decision "
                "was recorded."
            )

        else:
            st.dataframe(
                routing_df,
                use_container_width=True,
                hide_index=True,
            )

            selected = routing_df[
                routing_df["Selected"]
                == True
            ]

            if not selected.empty:
                departments = (
                    selected[
                        "Department"
                    ]
                    .drop_duplicates()
                    .tolist()
                )

                st.success(
                    "Selected specialty: "
                    + ", ".join(
                        departments
                    )
                )


# ============================================================
# VoI
# ============================================================

with tab_voi:
    st.subheader(
        "Value of Information"
    )

    voi_df = collect_voi(
        runtime
    )

    belief = selected_voi_belief(
        runtime
    )

    if belief:
        st.markdown(
            "### Final Diagnostic Belief"
        )

        belief_df = pd.DataFrame(
            {
                "Diagnosis": list(
                    belief.keys()
                ),
                "Probability": list(
                    belief.values()
                ),
            }
        ).set_index(
            "Diagnosis"
        )

        st.bar_chart(
            belief_df
        )

        st.dataframe(
            belief_df.reset_index(),
            use_container_width=True,
            hide_index=True,
        )

    if voi_df.empty:
        st.info(
            "No VoI candidate evaluation "
            "was recorded for this visit. "
            "This is expected for B0–B3."
        )

    else:
        st.markdown(
            "### Candidate Information Actions"
        )

        st.dataframe(
            voi_df,
            use_container_width=True,
            hide_index=True,
        )

        if "Selected" in voi_df.columns:
            selected_actions = voi_df[
                voi_df["Selected"] == True
            ]

            if not selected_actions.empty:
                st.markdown(
                    "### Selected Action"
                )

                for _, row in (
                    selected_actions.iterrows()
                ):
                    st.success(
                        f"{row['Action ID']}  |  "
                        f"VoI = "
                        f"{value_or_dash(row['VoI'], 4)}  |  "
                        f"IG = "
                        f"{value_or_dash(row['Information Gain'], 4)}"
                    )

    state = safe_dict(
        runtime.get("voi_state")
    )

    history = safe_list(
        state.get("history")
    )

    if history:
        with st.expander(
            "Raw VoI decision trace"
        ):
            st.json(
                history
            )


# ============================================================
# Footer
# ============================================================

st.divider()

st.caption(
    "Synthetic research visualization. "
    "This interface is for auditing and demonstrating the "
    "simulation decision process and does not represent "
    "clinical decision support."
)