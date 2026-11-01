import os
import tempfile
import unittest

from prediction_ledger import PredictionLedger, PredictionRecord, OutcomeRecord
from verified_backtest_report import report


class VerifiedBacktestReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "ledger.sqlite")

    def test_no_verified_pairs_does_not_invent_metrics(self):
        result = report(self.path)
        self.assertEqual(result["status"], "no_verified_pairs")
        self.assertIsNone(result["metrics"])

    def test_verified_pair_produces_real_metrics(self):
        ledger = PredictionLedger(self.path)
        ledger.record_prediction(PredictionRecord("fixture-1", "NBA", 100, 110, 100, 0.7))
        ledger.record_fixture_start("NBA", "fixture-1", 200)
        ledger.record_fixture_provenance("NBA", "fixture-1", "ESPN", "espn-1", 200)
        ledger.record_outcome(OutcomeRecord("fixture-1", "NBA", 300, 108, 104))
        result = report(self.path)
        self.assertEqual(result["status"], "evaluated")
        self.assertEqual(result["metrics"]["n_games"], 1)
        self.assertAlmostEqual(result["metrics"]["total_mae"], 2.0)
        self.assertAlmostEqual(result["metrics"]["home_win_brier"], 0.09)

    def test_missing_provenance_excluded(self):
        ledger = PredictionLedger(self.path)
        ledger.record_prediction(PredictionRecord("fixture-1", "NBA", 100, 110, 100, 0.7))
        ledger.record_fixture_start("NBA", "fixture-1", 200)
        ledger.record_outcome(OutcomeRecord("fixture-1", "NBA", 300, 108, 104))
        self.assertEqual(report(self.path)["status"], "no_verified_pairs")


if __name__ == "__main__":
    unittest.main()
