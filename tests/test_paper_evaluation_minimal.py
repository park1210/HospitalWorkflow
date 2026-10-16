import unittest
from app.core.paper_evaluation import episode_rows, paired


class PaperEvaluationTests(unittest.TestCase):
    def test_missing_runs_remain_in_denominator(self):
        cases = [{"longitudinal": {"patient_id": "p", "visit_id": "v"}}]
        row = episode_rows(cases, {'["p", "v"]': "A"}, None, "B0", 0)[0]
        self.assertEqual(row["correct_all_planned"], 0)
        self.assertIsNone(row["correct_completed"])
        self.assertIsNone(row["actions"])
        self.assertIsNone(row["tokens"])

    def test_patient_weighting_and_missing_pairs(self):
        rows = []
        for patient, visits, change in (("p1", 3, 1), ("p2", 1, 0)):
            for v in range(visits):
                for condition, value in (("B0", 0), ("B1", change)):
                    rows.append(dict(condition=condition, repeat=0, patient_id=patient, visit_id=str(v), score=value))
        result = paired(rows, "B0", "B1", "score")
        self.assertEqual(result["difference"], .5)
        self.assertEqual(result["patients"], 2)
        rows.pop()
        result = paired(rows, "B0", "B1", "score")
        self.assertIsNone(result["difference"])
        self.assertIsNone(result["ci95"])


if __name__ == "__main__":
    unittest.main()
