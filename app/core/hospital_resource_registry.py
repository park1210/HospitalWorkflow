from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class HospitalResource:
    resource_id: str
    resource_type: str
    location_id: str
    status: str = "idle"
    available_minute: int = 0
    assigned_case_id: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def is_available(self, current_minute: int) -> bool:
        return str(self.status).strip() == "idle" and int(self.available_minute or 0) <= int(current_minute or 0)

    @classmethod
    def from_summary(cls, payload: dict[str, Any]) -> "HospitalResource":
        item = dict(payload or {})
        return cls(
            resource_id=str(item.get("resource_id", "")).strip(),
            resource_type=str(item.get("resource_type", "")).strip(),
            location_id=str(item.get("location_id", "")).strip(),
            status=str(item.get("status", "")).strip() or "idle",
            available_minute=int(item.get("available_minute", 0) or 0),
            assigned_case_id=str(item.get("assigned_case_id", "")).strip(),
            meta=dict(item.get("meta", {}) or {}),
        )


@dataclass
class HospitalResourceRegistry:
    triage_nurses: list[HospitalResource] = field(default_factory=list)
    er_doctors: list[HospitalResource] = field(default_factory=list)
    er_beds: list[HospitalResource] = field(default_factory=list)
    lab_slots: list[HospitalResource] = field(default_factory=list)
    imaging_slots: list[HospitalResource] = field(default_factory=list)
    specialists: list[HospitalResource] = field(default_factory=list)
    consult_rooms: list[HospitalResource] = field(default_factory=list)

    @classmethod
    def default(cls) -> "HospitalResourceRegistry":
        specialists = [
            HospitalResource(resource_id=f"specialty_{department}", resource_type="specialist", location_id=f"sidebar_{sidebar}")
            for department, sidebar in (
                ("neurology", "neurology"),
                ("cardiology", "cardiology"),
                ("pulmonology", "pulmonology"),
                ("gastroenterology", "gastroenterology"),
                ("nephrology", "nephrology"),
                ("hematology", "hematology"),
                ("infectious_disease", "infectious_disease"),
                ("orthopedics", "orthopedics"),
                ("obstetrics_gynecology", "obgyn"),
                ("urology", "urology"),
                ("psychiatry", "psychiatry"),
                ("endocrinology", "endocrinology"),
                ("general_medicine", "general_medicine"),
                ("internal_medicine", "internal_medicine"),
                ("surgery", "surgery"),
            )
        ]
        return cls(
            triage_nurses=[HospitalResource(resource_id="nurse_triage_0", resource_type="triage_nurse", location_id="triage_desk")],
            er_doctors=[HospitalResource(resource_id="doctor_er_0", resource_type="er_doctor", location_id="er_doctor_station")],
            er_beds=[
                HospitalResource(resource_id="er_bed_1", resource_type="er_bed", location_id="er_bed_1"),
                HospitalResource(resource_id="er_bed_2", resource_type="er_bed", location_id="er_bed_2"),
                HospitalResource(resource_id="er_bed_3", resource_type="er_bed", location_id="er_bed_3"),
                HospitalResource(resource_id="er_bed_4", resource_type="er_bed", location_id="er_bed_4"),
            ],
            lab_slots=[
                HospitalResource(resource_id="lab_slot_1", resource_type="lab_slot", location_id="lab_station"),
                HospitalResource(resource_id="lab_slot_2", resource_type="lab_slot", location_id="lab_station"),
            ],
            imaging_slots=[
                HospitalResource(resource_id="imaging_slot_1", resource_type="imaging_slot", location_id="imaging_machine"),
            ],
            specialists=specialists,
            consult_rooms=[
                HospitalResource(resource_id="consult_room_1", resource_type="consult_room", location_id="specialty_consult_1"),
                HospitalResource(resource_id="consult_room_2", resource_type="consult_room", location_id="specialty_consult_2"),
                HospitalResource(resource_id="consult_room_3", resource_type="consult_room", location_id="specialty_consult_3"),
            ],
        )

    @classmethod
    def from_snapshot(cls, payload: dict[str, Any]) -> "HospitalResourceRegistry":
        snapshot = dict(payload or {})
        return cls(
            triage_nurses=[HospitalResource.from_summary(item) for item in list(snapshot.get("triage_nurses", []) or [])],
            er_doctors=[HospitalResource.from_summary(item) for item in list(snapshot.get("er_doctors", []) or [])],
            er_beds=[HospitalResource.from_summary(item) for item in list(snapshot.get("er_beds", []) or [])],
            lab_slots=[HospitalResource.from_summary(item) for item in list(snapshot.get("lab_slots", []) or [])],
            imaging_slots=[HospitalResource.from_summary(item) for item in list(snapshot.get("imaging_slots", []) or [])],
            specialists=[HospitalResource.from_summary(item) for item in list(snapshot.get("specialists", []) or [])],
            consult_rooms=[HospitalResource.from_summary(item) for item in list(snapshot.get("consult_rooms", []) or [])],
        )

    def resources_by_type(self, resource_type: str) -> list[HospitalResource]:
        mapping = {
            "triage_nurse": self.triage_nurses,
            "er_doctor": self.er_doctors,
            "er_bed": self.er_beds,
            "lab_slot": self.lab_slots,
            "imaging_slot": self.imaging_slots,
            "specialist": self.specialists,
            "consult_room": self.consult_rooms,
        }
        return list(mapping.get(str(resource_type).strip(), []))

    def first_available(self, resource_type: str, current_minute: int) -> HospitalResource | None:
        for resource in self.resources_by_type(resource_type):
            if resource.is_available(current_minute):
                return resource
        return None

    def find_by_id(self, resource_id: str) -> HospitalResource | None:
        for collection in (
            self.triage_nurses,
            self.er_doctors,
            self.er_beds,
            self.lab_slots,
            self.imaging_slots,
            self.specialists,
            self.consult_rooms,
        ):
            for resource in collection:
                if str(resource.resource_id).strip() == str(resource_id).strip():
                    return resource
        return None

    def release_case(self, case_id: str, current_minute: int) -> None:
        normalized_case_id = str(case_id).strip()
        for collection in (
            self.triage_nurses,
            self.er_doctors,
            self.lab_slots,
            self.imaging_slots,
            self.specialists,
            self.consult_rooms,
        ):
            for resource in collection:
                if str(resource.assigned_case_id).strip() != normalized_case_id:
                    continue
                resource.assigned_case_id = ""
                resource.status = "idle"
                resource.available_minute = int(current_minute or 0)

    def snapshot(self) -> dict[str, Any]:
        def serialize(resources: list[HospitalResource]) -> list[dict[str, Any]]:
            return [
                {
                    "resource_id": resource.resource_id,
                    "resource_type": resource.resource_type,
                    "location_id": resource.location_id,
                    "status": resource.status,
                    "available_minute": int(resource.available_minute or 0),
                    "assigned_case_id": resource.assigned_case_id,
                    "meta": dict(resource.meta or {}),
                }
                for resource in resources
            ]

        return {
            "triage_nurses": serialize(self.triage_nurses),
            "er_doctors": serialize(self.er_doctors),
            "er_beds": serialize(self.er_beds),
            "lab_slots": serialize(self.lab_slots),
            "imaging_slots": serialize(self.imaging_slots),
            "specialists": serialize(self.specialists),
            "consult_rooms": serialize(self.consult_rooms),
        }
