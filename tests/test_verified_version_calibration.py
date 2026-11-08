import os
import tempfile
import unittest

from prediction_ledger import PredictionLedger, PredictionRecord, OutcomeRecord
from verified_version_calibration import version_calibration_report


class VersionCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "ledger.sqlite")
        self.ledger = PredictionLedger(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_is_not_created(self):
        missing = os.path.join(self.tmp.name, "missing.sqlite")
        self.assertEqual(version_calibration_report(missing)["status"], "unavailable")
        self.assertFalse(os.path.exists(missing))

    def test_only_verified_pregame_versions_are_scored(self):
        for ts, home in ((100, 100.0), (120, 110.0), (160, 999.0)):
            self.ledger.record_prediction_version(PredictionRecord(
                "fixture-1", "NBA", ts, home, 100.0, 0.5))
        self.ledger.record_outcome(OutcomeRecord("fixture-1", "NBA", 200, 112, 98))
        self.ledger.record_fixture_start("NBA", "fixture-1", 150)
        self.ledger.record_fixture_provenance("NBA", "fixture-1", "ESPN", "espn-1", 150)
        report = version_calibration_report(self.path)
        self.assertEqual(report["verified_versions"], 2)
        self.assertEqual(report["excluded_versions"], 1)
        self.assertEqual(report["paired_fixture_count"], 1)
        self.assertAlmostEqual(report["metrics"]["paired_first_total_mae"], 10)
        self.assertAlmostEqual(report["metrics"]["paired_last_total_mae"], 0)

    def test_unverified_provider_is_excluded(self):
        self.ledger.record_prediction_version(PredictionRecord(
            "fixture-1", "NBA", 100, 110.0, 100.0, 0.5))
        self.ledger.record_outcome(OutcomeRecord("fixture-1", "NBA", 200, 112, 98))
        self.ledger.record_fixture_start("NBA", "fixture-1", 150)
        self.ledger.record_fixture_provenance("NBA", "fixture-1", "OTHER", "id", 150)
        self.assertEqual(version_calibration_report(self.path)["status"], "no_verified_versions")


if __name__ == "__main__":
    unittest.main()
