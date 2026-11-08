import os
import tempfile
import unittest

from calibration_readiness import audit_calibration_readiness
from prediction_ledger import PredictionLedger, PredictionRecord, OutcomeRecord


class CalibrationReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "ledger.sqlite")
        self.ledger = PredictionLedger(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_database_does_not_create_file(self):
        missing = os.path.join(self.temp.name, "missing.sqlite")
        self.assertEqual(audit_calibration_readiness(missing)["reason"], "ledger_not_found")
        self.assertFalse(os.path.exists(missing))

    def test_missing_outcome_and_provenance_blocks_readiness(self):
        self.ledger.record_prediction_version(PredictionRecord(
            "game", "NBA", 100, 110.0, 100.0, 0.55))
        self.ledger.record_fixture_start("NBA", "game", 150)
        result = audit_calibration_readiness(self.path)
        self.assertEqual(result["status"], "blocked")

    def test_verified_prematch_pair_enables_readiness(self):
        self.ledger.record_prediction_version(PredictionRecord(
            "game", "NBA", 100, 110.0, 100.0, 0.55))
        self.ledger.record_fixture_start("NBA", "game", 150)
        self.ledger.record_outcome(OutcomeRecord("game", "NBA", 200, 112, 98))
        self.ledger.record_fixture_provenance("NBA", "game", "ESPN", "espn-1", 150)
        result = audit_calibration_readiness(self.path)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["verified_versions"], 1)


if __name__ == "__main__":
    unittest.main()
