from __future__ import annotations

from typing import Any

from app.core.hospital_case_runtime import HospitalCaseRuntime
from app.utils.department_catalog import normalize_department


class HospitalSpecialtyPolicy:
    def plan_consult(
        self,
        runtime: HospitalCaseRuntime,
        *,
        specialist_id: str,
        consult_room_id: str,
    ) -> dict[str, Any]:
        department = normalize_department(str(runtime.target_department).strip(), default=runtime.target_department or "general_medicine")
        return {
            "department": department,
            "duration_min": self.consult_duration_minutes(runtime),
            "rationale": "The leading department still owned the unresolved evidence, so a specialty consult was started in the consult room.",
            "payload": {
                "department": department,
                "consult_room_id": str(consult_room_id).strip(),
                "specialist_id": str(specialist_id).strip(),
            },
        }

    def complete_consult(
        self,
        runtime: HospitalCaseRuntime,
        *,
        department: str,
        specialist_id: str,
    ) -> dict[str, Any]:
        normalized_department = normalize_department(str(department).strip(), default=runtime.target_department or "general_medicine")
        opinion = (
            f"{normalized_department} reviewed the ER evidence and agreed that the case can now be finalized "
            "without more repeated ER questioning."
        )
        final_diagnosis = str(runtime.assessment_summary).strip() or "undifferentiated acute complaint"
        rationale = "The specialty team completed focused review after ER stabilization and objective workup."
        return {
            "department": normalized_department,
            "consult_note": opinion,
            "rationale": rationale,
            "final_diagnosis": final_diagnosis,
            "payload": {
                "department": normalized_department,
                "consult_note": opinion,
                "specialist_id": str(specialist_id).strip(),
            },
        }

    @staticmethod
    def consult_duration_minutes(runtime: HospitalCaseRuntime) -> int:
        objective_count = len([str(item).strip() for item in list(runtime.objective_findings or []) if str(item).strip()])
        if objective_count >= 3:
            return 2
        return 3
