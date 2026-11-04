import unittest
from types import SimpleNamespace

from baseline_numeric_reconciliation import reconcile_team_average


class NumericReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            SimpleNamespace(ts_utc=i, timestamp_precision="exact",
                            pts_for=110.0, pts_against=105.0, pace=99.0)
            for i in range(1, 7)
        ]
        self.average = SimpleNamespace(points_for=110.0, points_against=105.0, pace=99.0)

    def test_matching_values(self):
        self.assertTrue(reconcile_team_average(self.average, self.rows, prediction_utc=10))

    def test_points_for_mismatch(self):
        self.average.points_for = 111.0
        with self.assertRaisesRegex(ValueError, "points_for"):
            reconcile_team_average(self.average, self.rows, prediction_utc=10)

    def test_points_against_mismatch(self):
        self.average.points_against = 106.0
        with self.assertRaisesRegex(ValueError, "points_against"):
            reconcile_team_average(self.average, self.rows, prediction_utc=10)

    def test_pace_mismatch(self):
        self.average.pace = 101.0
        with self.assertRaisesRegex(ValueError, "pace"):
            reconcile_team_average(self.average, self.rows, prediction_utc=10)

    def test_future_record_rejected(self):
        self.rows[-1].ts_utc = 10
        with self.assertRaisesRegex(ValueError, "point-in-time"):
            reconcile_team_average(self.average, self.rows, prediction_utc=10)

    def test_missing_numerical_evidence_rejected(self):
        self.rows[0].pace = None
        with self.assertRaisesRegex(ValueError, "finite"):
            reconcile_team_average(self.average, self.rows, prediction_utc=10)


if __name__ == "__main__":
    unittest.main()
