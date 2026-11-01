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
        self.assertEqual(result["audit"]["sample_size_assessment"], "no_verified_sample")
        self.assertIsNone(result["metrics"])
        self.assertIsNone(result["audit"]["verified_pair_coverage"])
        self.assertEqual(result["audit"]["excluded_matched_pairs"], 0)
        self.assertEqual(result["audit"]["exclusion_reasons"]["missing_provider_identity"], 0)

    def test_verified_pair_produces_real_metrics(self):
        ledger = PredictionLedger(self.path)
        ledger.record_prediction(PredictionRecord("fixture-1", "NBA", 100, 110, 100, 0.7))
        ledger.record_fixture_start("NBA", "fixture-1", 200)
        ledger.record_fixture_provenance("NBA", "fixture-1", "ESPN", "espn-1", 200)
        ledger.record_outcome(OutcomeRecord("fixture-1", "NBA", 300, 108, 104))
        result = report(self.path)
        self.assertEqual(result["status"], "evaluated")
        self.assertEqual(result["audit"]["sample_size_assessment"], "small_sample")
        self.assertEqual(result["metrics"]["n_games"], 1)
        self.assertIsNone(result["uncertainty"]["total_mae"])
        self.assertEqual(result["audit"]["verified_pair_coverage"], 1.0)
        self.assertEqual(sum(result["audit"]["primary_exclusion_reasons"].values()), 0)
        self.assertEqual(result["audit"]["excluded_matched_pairs"], 0)
        self.assertAlmostEqual(result["metrics"]["total_mae"], 2.0)
        self.assertAlmostEqual(result["metrics"]["home_win_brier"], 0.09)

    def test_invalid_league_rejected(self):
        with self.assertRaises(ValueError):
            report(self.path, "")
        with self.assertRaises(ValueError):
            report(self.path, None)

    def test_mismatched_provenance_start_excluded(self):
        ledger = PredictionLedger(self.path)
        ledger.record_prediction(PredictionRecord("fixture-1", "NBA", 100, 110, 100, 0.7))
        ledger.record_fixture_start("NBA", "fixture-1", 200)
        ledger.record_fixture_provenance("NBA", "fixture-1", "ESPN", "espn-1", 201)
        ledger.record_outcome(OutcomeRecord("fixture-1", "NBA", 300, 108, 104))
        result = report(self.path)
        self.assertEqual(result["status"], "no_verified_pairs")
        self.assertEqual(result["audit"]["provider_start_conflicts"], 1)
        self.assertEqual(result["audit"]["exclusion_reasons"]["provider_fixture_start_conflict"], 1)
        self.assertTrue(result["audit"]["exclusion_reason_counts_overlap"])
        self.assertEqual(result["audit"]["excluded_matched_pairs"], 1)
        self.assertEqual(result["audit"]["primary_exclusion_reasons"]["provider_fixture_start_conflict"], 1)
        self.assertEqual(result["audit"]["verified_pair_coverage"], 0.0)

    def test_prediction_after_tipoff_excluded(self):
        ledger = PredictionLedger(self.path)
        ledger.record_prediction(PredictionRecord("fixture-1", "NBA", 210, 110, 100, 0.7))
        ledger.record_fixture_start("NBA", "fixture-1", 200)
        ledger.record_fixture_provenance("NBA", "fixture-1", "ESPN", "espn-1", 200)
        ledger.record_outcome(OutcomeRecord("fixture-1", "NBA", 300, 108, 104))
        self.assertEqual(report(self.path)["status"], "no_verified_pairs")

    def test_two_verified_games_produce_uncertainty(self):
        ledger = PredictionLedger(self.path)
        for i in range(2):
            fixture = f"fixture-{i}"
            ledger.record_prediction(PredictionRecord(fixture, "NBA", 100, 110, 100, 0.7))
            ledger.record_fixture_start("NBA", fixture, 200)
            ledger.record_fixture_provenance("NBA", fixture, "ESPN", f"espn-{i}", 200)
            ledger.record_outcome(OutcomeRecord(fixture, "NBA", 300, 108 + i, 104))
        result = report(self.path)
        self.assertEqual(result["metrics"]["n_games"], 2)
        self.assertEqual(result["uncertainty"]["total_mae"]["n"], 2)
        self.assertAlmostEqual(result["uncertainty"]["total_mae"]["estimate"],
                               result["metrics"]["total_mae"])

    def test_missing_provenance_excluded(self):
        ledger = PredictionLedger(self.path)
        ledger.record_prediction(PredictionRecord("fixture-1", "NBA", 100, 110, 100, 0.7))
        ledger.record_fixture_start("NBA", "fixture-1", 200)
        ledger.record_outcome(OutcomeRecord("fixture-1", "NBA", 300, 108, 104))
        self.assertEqual(report(self.path)["status"], "no_verified_pairs")


if __name__ == "__main__":
    unittest.main()
