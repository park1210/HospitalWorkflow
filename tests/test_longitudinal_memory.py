from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from test_diagnostic_gate import Client, response, source
from app.core.clinical_observation import doctor_observation
from app.core.hospital_parallel_scheduler import HospitalParallelScheduler
from app.core.hospital_case_runtime import HospitalCaseRuntime
from app.core.longitudinal_memory import PatientMemoryStore, timestamp
from app.core.longitudinal_runner import run_longitudinal


def record(key="old", patient="p", visit="v1", date="2026-01-01T00:00:00Z", **extra):
    row = {"memory_id": key, "patient_id": patient, "visit_id": visit,
           "visit_started_at": date, "observed_at": date, "available_at": date,
           "source_id": "finding:0", "kind": "objective_finding", "text": "synthetic finding", "supersedes": []}
    row.update(extra)
    return row


IDENTITY = {"patient_id": "p", "visit_id": "v2", "started_at": "2026-02-01T00:00:00Z"}


class MemoryTests(unittest.TestCase):
    def test_patient_future_current_visit_and_late_availability_boundaries(self):
        store = PatientMemoryStore([record(), record("other", patient="q"),
            record("future", visit="v3", date="2026-03-01T00:00:00Z"),
            record("current", visit="v2"),
            record("late", available_at="2026-03-01T00:00:00Z")])
        rows = store.retrieve(IDENTITY, "synthetic", "full_history")["records"]
        self.assertEqual([r["memory_id"] for r in rows], ["old"])

    def test_supersession_only_takes_effect_when_known(self):
        store = PatientMemoryStore([record(), record("update", visit="v3", date="2026-03-01T00:00:00Z",
            kind="update", text="synthetic changed", supersedes=["old"])])
        self.assertEqual(store.retrieve(IDENTITY, "synthetic")["records"][0]["memory_id"], "old")
        later = {**IDENTITY, "visit_id": "v4", "started_at": "2026-04-01T00:00:00Z"}
        self.assertEqual([r["memory_id"] for r in store.retrieve(later, "synthetic")["records"]], ["update"])
        self.assertEqual(store.retrieve(later, "synthetic", "full_history")["records"][0]["status_as_of_visit"], "superseded")

    def test_cross_patient_update_and_duplicate_rejected(self):
        store = PatientMemoryStore([record()])
        with self.assertRaises(ValueError):
            store.add(record("update", patient="q", supersedes=["old"]))
        with self.assertRaises(ValueError):
            store.add(record())

    def test_timezones_and_chronology_validated(self):
        self.assertEqual(timestamp("2026-02-01T09:00:00+09:00"), timestamp(IDENTITY["started_at"]))
        with self.assertRaises(ValueError):
            timestamp("2026-02-01")
        with self.assertRaises(ValueError):
            PatientMemoryStore([record(available_at="2025-12-01T00:00:00Z")])

    def test_modes_and_retrieval_isolation(self):
        store = PatientMemoryStore([record(), record("irrelevant", text="unrelated")])
        self.assertEqual(store.retrieve(IDENTITY, "synthetic", "none")["records"], [])
        self.assertEqual(store.retrieve(IDENTITY, "synthetic", "full_history")["selected_count"], 2)
        selected = store.retrieve(IDENTITY, "synthetic")
        self.assertEqual(selected["selected_count"], 1)
        selected["records"][0]["text"] = "mutated"
        self.assertEqual(store.snapshot()["records"][0]["text"], "synthetic finding")
        self.assertEqual(store.retrieve(IDENTITY, "unknown")["selected_count"], 0)

    def test_persistence_round_trip(self):
        store = PatientMemoryStore([record()])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "memory.json"
            store.save(path)
            self.assertEqual(PatientMemoryStore.load(path).snapshot(), store.snapshot())

    def test_export_only_released_observations_and_label_prior_opinion(self):
        data = source()
        data["longitudinal"] = {**IDENTITY, "visit_id": "v1"}
        data["gold_label"] = {"diagnosis": "SECRET"}
        runtime = HospitalParallelScheduler().initialize([data]).case("gate")
        runtime.is_completed, runtime.final_diagnosis_min = True, 5
        runtime.assessment_summary = "prior opinion"
        runtime.objective_findings = ["T: released finding"]
        runtime.question_history = [{"answer": "unknown", "answer_status": "unknown"}]
        store = PatientMemoryStore()
        store.ingest_completed_visit(runtime)
        text = json.dumps(store.snapshot())
        self.assertNotIn("SECRET", text)
        self.assertNotIn("synthetic objective finding", text)  # unreleased source result
        self.assertIn("reported_not_verified", text)
        self.assertEqual(len(store.snapshot()["records"]), 2)
        with self.assertRaises(ValueError):
            store.ingest_completed_visit(runtime)

    def test_two_visit_runner_and_memory_modes(self):
        cases = []
        for n in (1, 2):
            data = source()
            data["case_id"] = f"case-{n}"
            data["longitudinal"] = {"patient_id": "p", "visit_id": f"v{n}", "started_at": f"2026-0{n}-01T00:00:00Z"}
            cases.append(data)
        original = deepcopy(cases)
        for mode in ("none", "full_history", "selective"):
            client = Client(response("request_test", target="T"), response(certainty="supported", indices=[0]),
                            response("request_test", target="T"), response(certainty="supported", indices=[0]))
            result = run_longitudinal(cases, mode=mode, client=client)
            self.assertEqual(result["status"], "completed")
            context = client.payloads[2]["observation"]["longitudinal_memory"]
            if mode == "none":
                self.assertEqual(context, {})
            else:
                self.assertTrue(context["records"])
                self.assertTrue(all(r["visit_id"] == "v1" for r in context["records"]))
            self.assertEqual(len(client.payloads), 4)  # memory adds no calls
            self.assertEqual(client.payloads[2]["supported_diagnosis_eligible_indices"], [])
        self.assertEqual(cases, original)

    def test_snapshot_preserves_memory_context(self):
        runtime = HospitalParallelScheduler().initialize([source()]).case("gate")
        runtime.memory_context = PatientMemoryStore([record()]).retrieve(IDENTITY, "synthetic")
        restored = HospitalCaseRuntime.from_summary(runtime.to_summary(), runtime.case_data)
        self.assertEqual(doctor_observation(runtime), doctor_observation(restored))

    def test_duplicate_visit_rejected_before_inference(self):
        data = source()
        data["longitudinal"] = IDENTITY
        client = Client()
        with self.assertRaises(ValueError):
            run_longitudinal([data, data], client=client)
        self.assertEqual(client.payloads, [])
