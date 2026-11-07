"""Regression tests for fail-closed calibration eligibility audit."""
import tempfile
import unittest
from pathlib import Path

from calibration_eligibility_audit import audit_calibration_eligibility
from prediction_ledger import PredictionLedger, PredictionRecord, OutcomeRecord


class CalibrationEligibilityAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = PredictionLedger(str(Path(self.tmp.name) / "ledger.sqlite"))

    def test_empty_ledger_never_claims_calibration(self):
        report = audit_calibration_eligibility(self.ledger)
        self.assertEqual(report["eligible_count"], 0)
        self.assertEqual(report["status"], "NO_VERIFIED_PREMATCH_PAIRS")

    def test_missing_original_input_snapshot_excludes_pair(self):
        ledger = self.ledger
        ledger.record_prediction(PredictionRecord("game1", "NBA", 100, 110, 100, None))
        ledger.record_outcome(OutcomeRecord("game1", "NBA", 300, 112, 99))
        ledger.record_fixture_start("NBA", "game1", 200)
        ledger.record_fixture_provenance("NBA", "game1", "ESPN", "provider-game1", 200)
        report = audit_calibration_eligibility(ledger)
        self.assertEqual(report["eligible_count"], 0)
        self.assertEqual(report["excluded"]["missing_prediction_inputs"], 1)

    def test_result_without_original_prediction_cannot_be_scored(self):
        self.ledger.record_outcome(OutcomeRecord("game2", "NBA", 300, 112, 99))
        report = audit_calibration_eligibility(self.ledger)
        self.assertEqual(report["predictions"], 0)
        self.assertEqual(report["outcomes"], 1)
        self.assertEqual(report["eligible_count"], 0)

    def test_post_tipoff_prediction_excluded(self):
        ledger = self.ledger
        ledger.record_prediction(PredictionRecord("game3", "NBA", 210, 110, 100, None))
        ledger.record_outcome(OutcomeRecord("game3", "NBA", 300, 112, 99))
        ledger.record_fixture_start("NBA", "game3", 200)
        report = audit_calibration_eligibility(ledger)
        self.assertEqual(report["excluded"]["invalid_timing"], 1)


if __name__ == "__main__":
    unittest.main()
