"""Adapter lineage/time checks; no model calls and no modifications to source JSONL."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

from app.data.synthea_adapter import convert_case, validate_case, serialized, safe_data

SOURCE = Path(__file__).resolve().parents[1] / "pilot_base_cases.jsonl"


class SyntheaAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.digest = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
        with SOURCE.open(encoding="utf-8") as f:
            cls.source = json.loads(next(f))
        # Small subset of actual input for fast edge checks; production conversion validated all 15.
        cls.source["past_visits"] = cls.source["past_visits"][:1]
        cls.source["past_visits"][0]["events"] = cls.source["past_visits"][0]["events"][:2]
        cls.source["current_encounter_events"] = cls.source["current_encounter_events"][:5]

    @classmethod
    def tearDownClass(cls):
        if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != cls.digest:
            raise AssertionError("Source changed")

    def convert(self, source=None):
        source = deepcopy(source or self.source)
        result = convert_case(source, SOURCE.name, self.digest)
        validate_case(source, result)
        return result

    def test_full_source_retained_and_no_complaint_invented(self):
        result = self.convert()
        self.assertEqual(result["source_past_visits"], self.source["past_visits"])
        self.assertEqual(result["source_current_encounter_events"], self.source["current_encounter_events"])
        self.assertNotIn("chief_complaint", result["current_initial_state"]["doctor_visible_info"])
        self.assertEqual(result["current_initial_state"]["patient_visible_info"], {})

    def test_annotations_cannot_affect_projection(self):
        original = self.convert()
        altered = deepcopy(self.source)
        altered.update(primary_specialty="other", acceptable_specialties=["other"],
                       gold_condition_code="SECRET", gold_condition_description="SECRET")
        result = self.convert(altered)
        for field in ("current_initial_state", "past_visits", "current_encounter_events"):
            self.assertEqual(original[field], result[field])
            self.assertNotIn("SECRET", serialized(result[field]))

    def test_date_only_current_has_no_inferred_minute(self):
        source = deepcopy(self.source)
        source["current_encounter_events"][0].update(event_time=source["index_encounter_start"][:10], time_precision="date")
        result = self.convert(source)
        eid = source["current_encounter_events"][0]["event_id"]
        self.assertIsNone(result["source_event_metadata"][eid]["available_minute"])
        self.assertNotIn(eid, {e["event_id"] for e in result["current_encounter_events"]})

    def test_past_original_timestamp_preserved_with_explicit_date_bound(self):
        result = self.convert()
        date_event = self.source["past_visits"][0]["events"][0]
        mid = self.source["patient_id"] + ":" + date_event["event_id"]
        self.assertEqual(result["past_record_metadata"][mid]["timestamp"], date_event["event_time"])
        self.assertEqual(result["past_record_metadata"][mid]["availability_policy"],
                         "date_upper_bound_next_midnight_not_occurrence_time")

    def test_no_ask_consult_or_invented_test_evidence(self):
        result = self.convert()
        lookup = {e["event_id"]: e for e in self.source["current_encounter_events"]}
        for event in result["current_encounter_events"]:
            self.assertEqual(event["action"], "Test")
            self.assertEqual(event["evidence"], serialized(safe_data(lookup[event["event_id"]])))

    def test_cross_patient_and_future_visit_rejected(self):
        source = deepcopy(self.source)
        source["past_visits"][0]["patient_id"] = "other"
        with self.assertRaises(ValueError):
            self.convert(source)
        source = deepcopy(self.source)
        source["past_visits"][0]["start_time"] = source["index_encounter_start"]
        with self.assertRaises(ValueError):
            self.convert(source)

    def test_reason_and_future_stop_not_in_memory_projection(self):
        source = deepcopy(self.source)
        source["past_visits"][0]["events"][0]["data"].update(
            reasondescription="SECRET", stop="2099-01-01")
        result = self.convert(source)
        text = result["past_visits"][0]["records"][0]["text"]
        self.assertNotIn("SECRET", text)
        self.assertNotIn("2099", text)
        self.assertEqual(result["source_past_visits"], source["past_visits"])


if __name__ == "__main__":
    unittest.main()
