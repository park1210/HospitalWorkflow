from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
from typing import Any

from app.core.hospital_case_runtime import HospitalCaseRuntime
from app.core.hospital_resource_registry import HospitalResourceRegistry


@dataclass
class HospitalSchedulerState:
    run_id: str = ""
    current_minute: int = 0
    tick: int = 0
    cases: dict[str, HospitalCaseRuntime] = field(default_factory=dict)
    resources: HospitalResourceRegistry = field(default_factory=HospitalResourceRegistry.default)
    arrival_queue: list[str] = field(default_factory=list)
    triage_queue: list[str] = field(default_factory=list)
    bed_queue: list[str] = field(default_factory=list)
    er_queue: list[str] = field(default_factory=list)
    test_queue: list[str] = field(default_factory=list)
    specialty_queue: list[str] = field(default_factory=list)
    scheduled_events: list[dict[str, Any]] = field(default_factory=list)
    event_log: list[dict[str, Any]] = field(default_factory=list)
    flow_config: dict[str, Any] = field(default_factory=dict)
    flow_accounting: dict[str, Any] = field(default_factory=dict)

    def active_case_ids(self) -> list[str]:
        return [case_id for case_id, case in self.cases.items() if not bool(case.is_completed)]

    @classmethod
    def from_snapshot(
        cls,
        snapshot: dict[str, Any],
        case_data_map: dict[str, dict[str, Any]] | None = None,
    ) -> "HospitalSchedulerState":
        payload = deepcopy(snapshot or {})
        cases_payload = dict(payload.get("cases", {}) or {})
        case_map = deepcopy(case_data_map or {})
        # Old snapshots did not retain the first contact timestamp. Recover only
        # from actual clinical events, never from dispatch/animation timestamps.
        for case_id, raw in list(cases_payload.items()):
            item = dict(raw)
            events = [e for e in payload.get("event_log", []) if e.get("case_id") == case_id]
            if "first_evaluation_min" not in item:
                minutes = [e["minute"] for e in events
                    if e.get("action") in {"ask_history", "order_test", "request_specialty", "er_finalize"}
                    and e.get("actor", {}).get("role") == "er_doctor"]
                item["first_evaluation_min"] = min(minutes) if minutes else None
            if "final_diagnosis_min" not in item:
                minutes = [e["minute"] for e in events if e.get("event_type") == "case_completed"]
                item["final_diagnosis_min"] = min(minutes) if minutes else None
            cases_payload[case_id] = item
        return cls(
            run_id=str(payload.get("run_id", "")).strip(),
            current_minute=int(payload.get("current_minute", 0) or 0),
            tick=int(payload.get("tick", 0) or 0),
            cases={
                str(case_id).strip(): HospitalCaseRuntime.from_summary(
                    dict(runtime or {}),
                    case_data=case_map.get(str(case_id).strip(), {}),
                )
                for case_id, runtime in cases_payload.items()
            },
            resources=HospitalResourceRegistry.from_snapshot(dict(payload.get("resources", {}) or {})),
            arrival_queue=[str(item).strip() for item in list(dict(payload.get("queues", {}) or {}).get("arrival_queue", []) or []) if str(item).strip()],
            triage_queue=[str(item).strip() for item in list(dict(payload.get("queues", {}) or {}).get("triage_queue", []) or []) if str(item).strip()],
            bed_queue=[str(item).strip() for item in list(dict(payload.get("queues", {}) or {}).get("bed_queue", []) or []) if str(item).strip()],
            er_queue=[str(item).strip() for item in list(dict(payload.get("queues", {}) or {}).get("er_queue", []) or []) if str(item).strip()],
            test_queue=[str(item).strip() for item in list(dict(payload.get("queues", {}) or {}).get("test_queue", []) or []) if str(item).strip()],
            specialty_queue=[str(item).strip() for item in list(dict(payload.get("queues", {}) or {}).get("specialty_queue", []) or []) if str(item).strip()],
            scheduled_events=[dict(item or {}) for item in list(payload.get("scheduled_events", []) or [])],
            event_log=[dict(item or {}) for item in list(payload.get("event_log", []) or [])],
            flow_config=deepcopy(payload.get("flow_config", {})),
            flow_accounting=deepcopy(payload.get("flow_accounting", {})),
        )

    def case(self, case_id: str) -> HospitalCaseRuntime:
        return self.cases[str(case_id).strip()]

    def queue_snapshot(self) -> dict[str, list[str]]:
        return {
            "arrival_queue": list(self.arrival_queue),
            "triage_queue": list(self.triage_queue),
            "bed_queue": list(self.bed_queue),
            "er_queue": list(self.er_queue),
            "test_queue": list(self.test_queue),
            "specialty_queue": list(self.specialty_queue),
        }

    def snapshot(self) -> dict[str, Any]:
        return deepcopy({
            "run_id": str(self.run_id).strip(),
            "current_minute": int(self.current_minute or 0),
            "tick": int(self.tick or 0),
            "cases": {case_id: runtime.to_summary() for case_id, runtime in self.cases.items()},
            "resources": self.resources.snapshot(),
            "queues": self.queue_snapshot(),
            "scheduled_events": [dict(event or {}) for event in self.scheduled_events],
            "event_log": [dict(event or {}) for event in self.event_log],
            "flow_config": deepcopy(self.flow_config),
            "flow_accounting": deepcopy(self.flow_accounting),
        })
