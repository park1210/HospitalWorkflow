from __future__ import annotations

from typing import Any

from app.agents.cardiology_agent import CardiologyAgent
from app.agents.er_department_agent import ERDepartmentAgent
from app.agents.gastroenterology_agent import GastroenterologyAgent
from app.agents.general_medicine_agent import GeneralMedicineAgent
from app.agents.hematology_agent import HematologyAgent
from app.agents.hospital_coordinator_agent import HospitalCoordinatorAgent
from app.agents.infectious_disease_agent import InfectiousDiseaseAgent
from app.agents.internal_medicine_agent import InternalMedicineAgent
from app.agents.nephrology_agent import NephrologyAgent
from app.agents.neurology_agent import NeurologyAgent
from app.agents.obstetrics_gynecology_agent import ObstetricsGynecologyAgent
from app.agents.orthopedics_agent import OrthopedicsAgent
from app.agents.patient_agent import PatientAgent
from app.agents.psychiatry_agent import PsychiatryAgent
from app.agents.pulmonology_agent import PulmonologyAgent
from app.agents.specialty_agent import DepartmentDiagnosticAgent
from app.agents.surgery_agent import SurgeryAgent
from app.agents.urology_agent import UrologyAgent
from app.core.evaluator import evaluate_department, evaluate_diagnosis
from app.core.logger import save_reasoning_state, save_trajectory, save_transcript
from app.core.metrics import build_resource_metrics, build_temporal_metrics
from app.core.reward import build_episode_reward_breakdown, finalize_trajectory
from app.core.event_schema import make_clinical_event
from app.core.state import (
    append_known_information,
    initialize_reasoning_state,
    record_consultation,
    record_clinical_event,
    record_decision,
    record_decision_snapshot,
    record_test_request,
    record_what_if_applied,
)
from app.core.time_engine import TimeEngine
from app.modules.diagnostic_reflection_module import DiagnosticReflectionModule
from app.modules.diagnosis_summary_module import DiagnosisSummaryModule
from app.modules.llm_self_reflection_module import LLMSelfReflectionModule
from app.utils.department_catalog import get_curated_department_assignment


GENERIC_DIAGNOSIS_PREFIXES = (
    "possible ",
    "undifferentiated",
    "acute abdominal",
    "possible acute",
    "possible central",
    "possible multisystem",
    "possible systemic",
    "possible infectious",
    "possible pulmonary",
    "possible cardiac",
    "possible urinary",
    "possible gynecologic",
    "possible bowel",
    "possible structural",
    "possible cerebellar",
    "possible neuromuscular junction",
    "possible neurologic process",
)


def _is_specific_diagnosis(diagnosis: str) -> bool:
    normalized = str(diagnosis).strip().lower()
    if not normalized:
        return False
    return not any(normalized.startswith(prefix) for prefix in GENERIC_DIAGNOSIS_PREFIXES)


def _can_finalize_in_er(state: Any) -> bool:
    if not _is_specific_diagnosis(state.er_working_diagnosis):
        return False
    objective_findings = list(state.objective_findings or [])
    if len(objective_findings) < 2:
        return False
    confidence = float(state.diagnostic_handoff_confidence or state.er_confidence or 0.0)
    if confidence < 0.85:
        return False
    routing_scores = dict(state.department_routing_scores or {})
    if routing_scores:
        ranked = sorted(routing_scores.items(), key=lambda item: item[1], reverse=True)
        if len(ranked) > 1 and (float(ranked[0][1]) - float(ranked[1][1])) < 1.5:
            return False
    return True


def _realign_department_from_final_diagnosis(final_decision: dict[str, Any]) -> dict[str, Any]:
    diagnosis = str(final_decision.get("final_diagnosis", "")).strip()
    if not _is_specific_diagnosis(diagnosis):
        return final_decision

    assignment = get_curated_department_assignment(diagnosis)
    if not assignment:
        return final_decision

    curated_department = str(assignment.get("department", "")).strip()
    if not curated_department:
        return final_decision

    current_department = str(final_decision.get("final_department", "")).strip()
    if curated_department == current_department:
        return final_decision

    rationale = str(final_decision.get("finalization_rationale", "")).strip()
    ownership_note = (
        f" Final department aligned to {curated_department} because curated ownership for "
        f"'{diagnosis}' indicates this service is the primary diagnostic owner."
    )
    final_decision["final_department"] = curated_department
    final_decision["diagnostic_service"] = curated_department
    final_decision["finalization_rationale"] = f"{rationale}{ownership_note}".strip()
    final_decision["department_alignment_source"] = "curated_diagnosis_department_map"
    return final_decision


def _event_location_id(action: str, target: str = "") -> str:
    normalized_action = str(action).strip().lower()
    normalized_target = str(target).strip().lower()
    if normalized_action in {"perform_triage"}:
        return "triage_desk"
    if normalized_action in {"perform_assessment", "ask_patient"}:
        return "er_bed_1"
    if normalized_action in {"request_test", "await_test_results", "test_started", "test_completed", "result_received"}:
        if any(token in normalized_target for token in ("blood", "lab", "panel", "culture", "urine")):
            return "lab_station"
        return "imaging_wait_1"
    if normalized_action in {"observe_patient"}:
        return "observation_bed_1"
    if normalized_action in {"make_diagnostic_summary", "consult_before_handoff", "consulting", "diagnose", "reroute_department", "refine_again"}:
        return "specialty_consult_1"
    if normalized_action in {"discharge", "case_completed"}:
        return "discharge_1"
    return ""


def _emit_structured_event(
    state: Any,
    run_id: str,
    *,
    phase: str,
    actor: str,
    action: str,
    target: str = "",
    rationale: str = "",
    payload: dict[str, Any] | None = None,
    state_delta: dict[str, Any] | None = None,
    event_type: str,
    actor_role: str,
    target_id: str = "",
    target_role: str = "",
    resource_kind: str = "",
    meta: dict[str, Any] | None = None,
) -> None:
    event = make_clinical_event(
        run_id=run_id,
        case_id=str(getattr(state, "case_id", "")).strip(),
        minute=int(getattr(state, "current_time_min", 0) or 0),
        tick=int(getattr(state, "turn_count", 0) or 0),
        phase=str(phase).strip(),
        actor_id=str(actor).strip(),
        actor_role=str(actor_role).strip(),
        target_id=str(target_id).strip(),
        target_role=str(target_role).strip(),
        event_type=event_type,  # type: ignore[arg-type]
        action=str(action).strip(),
        location_id=_event_location_id(action, target),
        resource_kind=str(resource_kind).strip(),
        rationale=str(rationale).strip(),
        payload=dict(payload or {}),
        state_delta=dict(state_delta or {}),
        meta=dict(meta or {}),
        ordinal=len(list(getattr(state, "event_log", []) or [])),
    )
    record_clinical_event(state, event)


def run_single_case(
    case: dict[str, Any],
    run_id: str,
    max_turns: int,
    what_if_override: dict[str, Any] | None = None,
    initial_time_offset_min: int = 0,
    shared_resource_state: dict[str, Any] | None = None,
    live_observer: Any | None = None,
    queue_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = initialize_reasoning_state(case)

    def observe_and_forward(payload: dict[str, Any]) -> None:
        phase = str(payload.get("phase", "")).strip()
        actor = str(payload.get("actor", "")).strip()
        action = str(payload.get("action", "")).strip()
        target = str(payload.get("target", "")).strip()
        conversation_lines = [str(line).strip() for line in list(payload.get("conversation_lines", []) or []) if str(line).strip()]
        actor_role = "system" if actor == "system" else ("er" if actor == "er_department" else "specialty")
        zone = ""
        state_payload = dict(payload.get("state", {}) or {})
        pending_results_count = len(list(state_payload.get("pending_results", []) or []))
        if phase == "case_started":
            _emit_structured_event(
                state,
                run_id,
                phase=phase,
                actor=actor or "system",
                action=action or "case_started",
                event_type="case_started",
                actor_role="system",
                target_id=f"patient_{state.case_id}",
                target_role="patient",
                state_delta={"zone": "waiting_room"},
            )
        elif action == "perform_triage":
            _emit_structured_event(
                state,
                run_id,
                phase=phase,
                actor="doctor_er_0",
                action=action,
                rationale=str(getattr(state, "latest_rationale", "")).strip(),
                event_type="triage_completed",
                actor_role="er",
                target_id=f"patient_{state.case_id}",
                target_role="patient",
                resource_kind="doctor",
                state_delta={"zone": "er_workup", "triage_level": int(getattr(state, "triage_level", 3) or 3)},
            )
        elif action == "perform_assessment":
            _emit_structured_event(
                state,
                run_id,
                phase=phase,
                actor="doctor_er_0",
                action=action,
                rationale=str(getattr(state, "latest_rationale", "")).strip(),
                event_type="assessment_completed",
                actor_role="er",
                target_id=f"patient_{state.case_id}",
                target_role="patient",
                resource_kind="doctor",
                state_delta={"zone": "er_workup"},
            )
        elif action == "ask_patient":
            question = ""
            answer = ""
            for line in conversation_lines:
                lowered = line.lower()
                if lowered.startswith("er:") or lowered.startswith("specialist:"):
                    question = line.split(":", 1)[-1].strip()
                elif lowered.startswith("patient:"):
                    answer = line.split(":", 1)[-1].strip()
            if question:
                _emit_structured_event(
                    state,
                    run_id,
                    phase=phase,
                    actor="doctor_er_0" if actor == "er_department" else actor,
                    action=action,
                    rationale=str(getattr(state, "latest_rationale", "")).strip(),
                    event_type="question_asked",
                    actor_role="er" if actor == "er_department" else "specialty",
                    target_id=f"patient_{state.case_id}",
                    target_role="patient",
                    resource_kind="doctor",
                    payload={"question": question},
                    state_delta={"zone": "specialty_review" if actor != "er_department" else "er_workup"},
                )
            if answer:
                _emit_structured_event(
                    state,
                    run_id,
                    phase=phase,
                    actor=f"patient_{state.case_id}",
                    action="answer_patient",
                    rationale=str(getattr(state, "latest_rationale", "")).strip(),
                    event_type="answer_received",
                    actor_role="patient",
                    target_id="doctor_er_0" if actor == "er_department" else actor,
                    target_role="er" if actor == "er_department" else "specialty",
                    payload={"answer": answer},
                    state_delta={"zone": "specialty_review" if actor != "er_department" else "er_workup"},
                )
        elif action in {"request_test"}:
            _emit_structured_event(
                state,
                run_id,
                phase=phase,
                actor="doctor_er_0" if actor == "er_department" else actor,
                action=action,
                target=target,
                rationale=str(getattr(state, "latest_rationale", "")).strip(),
                event_type="test_ordered",
                actor_role="er" if actor == "er_department" else "specialty",
                target_id=f"patient_{state.case_id}",
                target_role="patient",
                resource_kind="doctor",
                payload={"requested_test": target},
                state_delta={"zone": "awaiting_results", "pending_results_count": pending_results_count},
            )
        elif action == "await_test_results":
            _emit_structured_event(
                state,
                run_id,
                phase=phase,
                actor="doctor_er_0",
                action=action,
                rationale=str(getattr(state, "latest_rationale", "")).strip(),
                event_type="result_received",
                actor_role="er",
                target_id=f"patient_{state.case_id}",
                target_role="patient",
                resource_kind="lab",
                payload={"pending_results_count": pending_results_count},
                state_delta={"zone": "awaiting_results", "pending_results_count": pending_results_count},
            )
        elif action in {"make_diagnostic_summary", "consult_before_handoff"}:
            zone = "specialty_review"
            _emit_structured_event(
                state,
                run_id,
                phase=phase,
                actor="doctor_er_0",
                action=action,
                target=target,
                rationale=str(getattr(state, "latest_rationale", "")).strip(),
                event_type="consult_requested",
                actor_role="er",
                target_id=f"specialty_{target}" if target else "",
                target_role="specialty",
                resource_kind="consult",
                payload={"department": target},
                state_delta={"zone": zone},
            )
        elif action == "observe_patient":
            _emit_structured_event(
                state,
                run_id,
                phase=phase,
                actor="doctor_er_0",
                action=action,
                rationale=str(getattr(state, "latest_rationale", "")).strip(),
                event_type="observation_started",
                actor_role="er",
                target_id=f"patient_{state.case_id}",
                target_role="patient",
                resource_kind="doctor",
                state_delta={"zone": "observation"},
            )
        elif action in {"consulting", "refine_again", "reroute_department"}:
            _emit_structured_event(
                state,
                run_id,
                phase=phase,
                actor=f"specialty_{actor}",
                action=action,
                target=target,
                rationale=str(getattr(state, "latest_rationale", "")).strip(),
                event_type="consult_note_added" if action != "consulting" else "consult_started",
                actor_role="specialty",
                target_id=f"patient_{state.case_id}",
                target_role="patient",
                resource_kind="consult",
                state_delta={"zone": "specialty_review"},
            )
        elif action == "diagnose":
            _emit_structured_event(
                state,
                run_id,
                phase=phase,
                actor=f"specialty_{actor}" if actor and actor != "er_department" else "doctor_er_0",
                action=action,
                rationale=str(getattr(state, "latest_rationale", "")).strip(),
                event_type="diagnosis_finalized",
                actor_role="specialty" if actor and actor != "er_department" else "er",
                target_id=f"patient_{state.case_id}",
                target_role="patient",
                payload={"diagnosis": str(getattr(state, "final_diagnosis", "") or getattr(state, "er_working_diagnosis", "")).strip()},
                state_delta={"zone": "completed"},
            )
        elif phase == "case_completed":
            _emit_structured_event(
                state,
                run_id,
                phase=phase,
                actor="system",
                action=action or "case_completed",
                event_type="case_completed",
                actor_role="system",
                target_id=f"patient_{state.case_id}",
                target_role="patient",
                payload={
                    "final_diagnosis": str(getattr(state, "final_diagnosis", "")).strip(),
                    "final_department": str(getattr(state, "final_department", "")).strip(),
                },
                state_delta={"zone": "completed"},
            )

        if callable(live_observer):
            live_observer(payload)

    def emit_live_update(
        *,
        phase: str,
        actor: str,
        action: str,
        target: str = "",
        conversation_lines: list[str] | None = None,
    ) -> None:
        if not callable(live_observer):
            return
        observe_and_forward(
            {
                "case_id": state.case_id,
                "run_id": run_id,
                "phase": phase,
                "actor": actor,
                "action": str(action).strip(),
                "target": str(target).strip(),
                "queue_context": dict(queue_context or {}),
                "state": state.to_dict(),
                "transcript_tail": list(transcript[-6:]) if "transcript" in locals() else [],
                "conversation_lines": list(conversation_lines or []),
            }
        )

    coordinator = HospitalCoordinatorAgent()
    patient_agent = PatientAgent(case)
    time_engine = TimeEngine(shared_resource_state=shared_resource_state)
    er_department_agent = ERDepartmentAgent(
        case,
        patient_agent,
        what_if_override=what_if_override,
        time_engine=time_engine,
        live_observer=observe_and_forward,
    )
    if initial_time_offset_min > state.arrival_time_min:
        time_engine.advance_passive_time(
            case,
            state,
            minutes=initial_time_offset_min - int(state.arrival_time_min or 0),
            reason=(
                f"The patient waited {initial_time_offset_min - int(state.arrival_time_min or 0)} minutes "
                "before active ER evaluation began."
            ),
        )
    department_agents = {
        "general_medicine": GeneralMedicineAgent(),
        "internal_medicine": InternalMedicineAgent(),
        "neurology": NeurologyAgent(),
        "surgery": SurgeryAgent(),
        "cardiology": CardiologyAgent(),
        "pulmonology": PulmonologyAgent(),
        "gastroenterology": GastroenterologyAgent(),
        "nephrology": NephrologyAgent(),
        "hematology": HematologyAgent(),
        "infectious_disease": InfectiousDiseaseAgent(),
        "orthopedics": OrthopedicsAgent(),
        "obstetrics_gynecology": ObstetricsGynecologyAgent(),
        "urology": UrologyAgent(),
        "psychiatry": PsychiatryAgent(),
    }
    diagnosis_summary_module = DiagnosisSummaryModule()
    reflection_module = DiagnosticReflectionModule()
    llm_self_reflection_module = LLMSelfReflectionModule()

    transcript: list[dict[str, str]] = [
        {"role": "system", "content": f"Hospital diagnosis workflow start: {case.get('doctor_visible_info', {})}"}
    ]
    emit_live_update(phase="case_started", actor="system", action="case_started")

    entry_assignment = coordinator.assign_entry_department(case)
    transcript.append({"role": "hospital_coordinator", "content": str(entry_assignment)})

    er_department_agent.run(state, transcript, max_turns)

    er_reflection = reflection_module.review("post_er", state.to_dict())
    transcript.append({"role": "diagnostic_reflection", "content": str(er_reflection)})
    if er_reflection.get("applied"):
        for key, value in er_reflection.get("updates", {}).items():
            setattr(state, key, value)
        state.reflection_count += 1
        state.reflection_triggers.extend(
            trigger for trigger in er_reflection.get("triggers", []) if trigger not in state.reflection_triggers
        )
    record_decision(state, "diagnostic_reflection", "post_er_review", str(er_reflection.get("rationale", "")).strip())

    llm_er_reflection = llm_self_reflection_module.review("post_er", state.to_dict(), transcript)
    transcript.append({"role": "llm_self_reflection", "content": str(llm_er_reflection)})
    if llm_er_reflection.get("used_llm"):
        state.llm_call_count += 1
        state.llm_self_reflection_count += 1
    if llm_er_reflection.get("applied"):
        for key, value in llm_er_reflection.get("updates", {}).items():
            setattr(state, key, value)
        state.reflection_count += 1
        state.reflection_triggers.extend(
            trigger for trigger in llm_er_reflection.get("triggers", []) if trigger not in state.reflection_triggers
        )
    record_decision(
        state,
        "llm_self_reflection",
        "post_er_review",
        str(llm_er_reflection.get("rationale", "")).strip(),
    )

    er_can_finalize = _can_finalize_in_er(state)
    service_name = str(state.diagnostic_service or state.responsible_department or "general_medicine").strip()

    if er_can_finalize:
        diagnosis_summary = diagnosis_summary_module.build(state.to_dict(), transcript)
        transcript.append({"role": "diagnosis_summary", "content": str(diagnosis_summary)})
        final_decision = {
            "final_diagnosis": state.er_working_diagnosis,
            "final_department": str(state.responsible_department or service_name or "general_medicine").strip(),
            "diagnostic_service": service_name or str(state.responsible_department or "general_medicine").strip(),
            "finalization_rationale": state.diagnostic_handoff_rationale or "The ER finalized the diagnosis because objective evidence already supported a specific answer.",
            "final_decision_source": "er_department",
        }
        final_decision = _realign_department_from_final_diagnosis(final_decision)
        transcript.append({"role": "final_diagnosis", "content": str(final_decision)})
    else:
        diagnostic_service = coordinator.choose_diagnostic_service(state.to_dict())
        state.diagnostic_service = str(diagnostic_service.get("diagnostic_service", "")).strip() or state.diagnostic_service
        state.responsible_department = (
            str(diagnostic_service.get("responsible_department", "")).strip() or state.responsible_department
        )
        transcript.append({"role": "hospital_coordinator", "content": str(diagnostic_service)})

        service_name = str(diagnostic_service["diagnostic_service"]).strip()
        department_agent = department_agents.get(service_name)
        if department_agent is None and service_name:
            department_agent = DepartmentDiagnosticAgent(service_name)

        if department_agent is not None:
            specialty_plan = department_agent.accept_handoff(
                state.to_dict(),
                transcript,
                patient_agent=patient_agent,
                test_module=er_department_agent.test_module,
                max_turns=2,
                what_if_override=what_if_override,
            )
            transcript.append({"role": service_name, "content": str(specialty_plan)})
            for snapshot in specialty_plan.get("decision_snapshots", []) or []:
                if isinstance(snapshot, dict):
                    record_decision_snapshot(state, snapshot)
            if isinstance(specialty_plan.get("what_if_applied_event"), dict):
                record_what_if_applied(state, dict(specialty_plan.get("what_if_applied_event") or {}))
            if specialty_plan.get("llm_attempted"):
                state.specialty_llm_attempt_count += 1
                state.specialty_llm_debug.append(
                    {
                        "service": service_name,
                        "used_llm": bool(specialty_plan.get("used_llm", False)),
                        "failure_reason": str(specialty_plan.get("llm_failure_reason", "")).strip(),
                        "response_preview": str(specialty_plan.get("llm_response_preview", "")).strip(),
                        "candidate_diagnoses": list(specialty_plan.get("llm_candidate_diagnoses", []) or []),
                    }
                )
                transcript.append(
                    {
                        "role": f"{service_name}_llm_debug",
                        "content": str(
                            {
                                "used_llm": bool(specialty_plan.get("used_llm", False)),
                                "failure_reason": str(specialty_plan.get("llm_failure_reason", "")).strip(),
                                "response_preview": str(specialty_plan.get("llm_response_preview", "")).strip(),
                                "candidate_diagnoses": list(specialty_plan.get("llm_candidate_diagnoses", []) or []),
                            }
                        ),
                    }
                )
            if specialty_plan.get("used_llm"):
                state.llm_call_count += 1
                state.specialty_llm_success_count += 1
            elif specialty_plan.get("llm_failure_reason"):
                failure_reason = str(specialty_plan.get("llm_failure_reason", "")).strip()
                if failure_reason:
                    state.specialty_llm_failures.append(f"{service_name}:{failure_reason}")
            for step in specialty_plan.get("specialty_steps", []) or []:
                action = str(step.get("action", "")).strip()
                rationale = str(step.get("rationale", "")).strip()
                if action:
                    record_decision(state, service_name, action, rationale)
                    transcript.append({"role": f"{service_name}_step", "content": str(step)})

                if action == "ask_patient":
                    answer = str(step.get("answer", "")).strip()
                    if answer:
                        append_known_information(state, answer)

                if action == "request_test":
                    requested_test = str(step.get("requested_test", "")).strip()
                    resolved_name = str(step.get("resolved_name", "")).strip() or requested_test
                    result_text = str(step.get("result_text", "")).strip()
                    if requested_test:
                        record_test_request(state, requested_test)
                    finding = f"{resolved_name}: {result_text}".strip()
                    if result_text:
                        append_known_information(state, finding)
                        if finding not in state.objective_findings:
                            state.objective_findings.append(finding)

                if action == "consult_specialty":
                    consult_department = str(step.get("consult_department", "")).strip()
                    opinion = str(step.get("opinion", "")).strip()
                    if consult_department:
                        record_consultation(state, consult_department, opinion)
                    if opinion:
                        append_known_information(state, f"{consult_department} consult: {opinion}" if consult_department else opinion)

                if action:
                    specialty_conversation_lines: list[str] = []
                    if action == "ask_patient":
                        question = str(step.get("question", "")).strip()
                        answer = str(step.get("answer", "")).strip()
                        if question:
                            specialty_conversation_lines.append(f"Specialist: {question}")
                        if answer:
                            specialty_conversation_lines.append(f"Patient: {answer}")
                    elif action == "request_test":
                        requested_test = str(step.get("requested_test", "") or step.get("target", "")).strip()
                        if requested_test:
                            specialty_conversation_lines.append(
                                f"Specialist: I need a focused {requested_test} before I finalize this."
                            )
                    elif action == "refine_again":
                        diagnosis = str(step.get("diagnosis", "")).strip()
                        if diagnosis:
                            specialty_conversation_lines.append(
                                f"Specialist: The picture is still evolving, so I want to refine beyond {diagnosis}."
                            )
                    elif action == "diagnose":
                        diagnosis = str(step.get("diagnosis", "")).strip()
                        if diagnosis:
                            specialty_conversation_lines.append(
                                f"Specialist: Based on the ER workup and specialty review, this is most consistent with {diagnosis}."
                            )
                    elif action == "reroute_department":
                        to_department = str(step.get("to_department", "")).strip()
                        diagnosis = str(step.get("diagnosis", "")).strip()
                        if to_department:
                            specialty_conversation_lines.append(
                                f"Specialist: This fits {diagnosis or 'the case'} better under {to_department}."
                            )
                    time_engine.advance_time(
                        case,
                        state,
                        actor=service_name,
                        action=action,
                        target=str(step.get("requested_test", "")).strip()
                        or str(step.get("consult_department", "")).strip()
                        or str(step.get("to_department", "")).strip(),
                        rationale=rationale,
                    )
                    emit_live_update(
                        phase="specialty_step",
                        actor=service_name,
                        action=action,
                        target=str(step.get("requested_test", "")).strip()
                        or str(step.get("consult_department", "")).strip()
                        or str(step.get("to_department", "")).strip(),
                        conversation_lines=specialty_conversation_lines,
                    )

            state.diagnostic_service = str(specialty_plan.get("accepting_service", "")).strip() or state.diagnostic_service
            state.responsible_department = (
                str(specialty_plan.get("responsible_department", "")).strip() or state.responsible_department
            )
            refined_diagnosis = str(specialty_plan.get("refined_diagnosis", "")).strip()
            if refined_diagnosis:
                state.er_working_diagnosis = refined_diagnosis
        else:
            specialty_plan = {
                "accepting_service": service_name,
                "responsible_department": diagnostic_service["responsible_department"],
                "diagnostic_plan": "Specialty diagnostic review completed after ER workup.",
            }
            transcript.append({"role": "specialty_service", "content": str(specialty_plan)})

        specialty_reflection = reflection_module.review("post_specialty", state.to_dict())
        transcript.append({"role": "diagnostic_reflection", "content": str(specialty_reflection)})
        if specialty_reflection.get("applied"):
            for key, value in specialty_reflection.get("updates", {}).items():
                setattr(state, key, value)
            state.reflection_count += 1
            state.reflection_triggers.extend(
                trigger for trigger in specialty_reflection.get("triggers", []) if trigger not in state.reflection_triggers
            )
        record_decision(
            state,
            "diagnostic_reflection",
            "post_specialty_review",
            str(specialty_reflection.get("rationale", "")).strip(),
        )

        llm_specialty_reflection = llm_self_reflection_module.review("post_specialty", state.to_dict(), transcript)
        transcript.append({"role": "llm_self_reflection", "content": str(llm_specialty_reflection)})
        if llm_specialty_reflection.get("used_llm"):
            state.llm_call_count += 1
            state.llm_self_reflection_count += 1
        if llm_specialty_reflection.get("applied"):
            for key, value in llm_specialty_reflection.get("updates", {}).items():
                setattr(state, key, value)
            state.reflection_count += 1
            state.reflection_triggers.extend(
                trigger
                for trigger in llm_specialty_reflection.get("triggers", [])
                if trigger not in state.reflection_triggers
            )
        record_decision(
            state,
            "llm_self_reflection",
            "post_specialty_review",
            str(llm_specialty_reflection.get("rationale", "")).strip(),
        )

        diagnosis_summary = diagnosis_summary_module.build(state.to_dict(), transcript)
        transcript.append({"role": "diagnosis_summary", "content": str(diagnosis_summary)})
        final_decision = {
            "final_diagnosis": state.er_working_diagnosis or "undifferentiated acute complaint",
            "final_department": str(state.responsible_department or service_name or "general_medicine").strip(),
            "diagnostic_service": str(state.diagnostic_service or service_name or state.responsible_department or "general_medicine").strip(),
            "finalization_rationale": str(specialty_plan.get("diagnostic_plan", "")).strip()
            or state.diagnostic_handoff_rationale
            or "The specialty department finalized the diagnosis after ER workup.",
            "final_decision_source": "specialty_department",
        }
        final_decision = _realign_department_from_final_diagnosis(final_decision)
        transcript.append({"role": "final_diagnosis", "content": str(final_decision)})

    state.final_diagnosis = str(final_decision.get("final_diagnosis", "")).strip() or state.er_working_diagnosis or "undifferentiated acute complaint"
    state.final_department = str(final_decision.get("final_department", "")).strip() or state.responsible_department or "general_medicine"
    state.diagnostic_service = str(final_decision.get("diagnostic_service", "")).strip() or service_name
    state.final_decision_source = str(final_decision.get("final_decision_source", "")).strip() or "hospital_diagnosis_workflow"
    state.latest_rationale = str(final_decision.get("finalization_rationale", "")).strip() or state.latest_rationale
    state.chief_doctor_called = False

    handoff = coordinator.finalize_route(state.to_dict())
    transcript.append({"role": "hospital_coordinator", "content": str(handoff)})

    episode_reward_breakdown = build_episode_reward_breakdown(
        case,
        state.to_dict(),
        state.final_diagnosis,
        state.final_department,
    )
    trajectory_steps, episode_reward = finalize_trajectory(
        state.trajectory_steps,
        episode_reward_breakdown,
    )
    state.trajectory_steps = trajectory_steps
    state.reward_breakdown = episode_reward_breakdown
    state.episode_reward = round(episode_reward, 4)

    gold = case.get("gold_label", {})
    department_correct = evaluate_department(state.final_department, str(gold.get("department", "")))
    temporal_metrics = build_temporal_metrics(state.to_dict())
    resource_metrics = build_resource_metrics(state.to_dict())
    result = {
        "case_id": case.get("case_id", ""),
        "triage_level": state.triage_level,
        "predicted_diagnosis": state.final_diagnosis,
        "predicted_department": state.final_department,
        "diagnostic_service": state.diagnostic_service,
        "er_working_diagnosis": state.er_working_diagnosis,
        "final_decision_source": state.final_decision_source,
        "ground_truth": gold.get("diagnosis", ""),
        "ground_truth_department": gold.get("department", ""),
        "diagnosis_correct": evaluate_diagnosis(state.final_diagnosis, str(gold.get("diagnosis", ""))),
        "department_correct": department_correct,
        "department_evaluable": bool(gold.get("department_evaluable", str(gold.get("department", "")).strip())),
        "episode_reward": state.episode_reward,
        "reward_breakdown": state.reward_breakdown,
        "temporal_metrics": temporal_metrics,
        "resource_metrics": resource_metrics,
        "what_if_summary": {
            "shadow_event_count": len(state.what_if_shadow_events),
            "shadow_disagreement_count": int((state.what_if_stats or {}).get("shadow_disagreement_count", 0) or 0),
            "applied_event_count": len(state.what_if_applied_events),
            "decision_snapshot_count": len(state.decision_snapshots),
            "replay_count": len(state.what_if_replay_history),
        },
        "event_log": list(state.event_log),
        "decision_snapshots": state.decision_snapshots,
        "transcript": transcript,
        "reasoning_state": state.to_dict(),
    }
    emit_live_update(phase="case_completed", actor="system", action="case_completed")

    save_transcript(str(case.get("case_id", "")), transcript, run_id)
    save_reasoning_state(str(case.get("case_id", "")), state.to_dict(), run_id)
    save_trajectory(
        str(case.get("case_id", "")),
        {
            "case_id": case.get("case_id", ""),
            "episode_reward": state.episode_reward,
            "reward_breakdown": state.reward_breakdown,
            "final_decision_source": state.final_decision_source,
            "temporal_metrics": temporal_metrics,
            "resource_metrics": resource_metrics,
            "steps": state.trajectory_steps,
        },
        run_id,
    )
    return result
