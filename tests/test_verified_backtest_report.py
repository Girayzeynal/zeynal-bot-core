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
        self.assertEqual(result["uncertainty"]["block_length_sensitivity"]["eligible_block_lengths"], 0)

    def test_non_espn_verified_fixture_refuses_mixed_report(self):
        ledger = PredictionLedger(self.path)
        for fixture, provider in (("fixture-espn", "ESPN"), ("fixture-other", "OTHER")):
            ledger.record_prediction(PredictionRecord(fixture, "NBA", 100, 110, 100, 0.7))
            ledger.record_fixture_start("NBA", fixture, 200)
            ledger.record_fixture_provenance("NBA", fixture, provider, fixture, 200)
            ledger.record_outcome(OutcomeRecord(fixture, "NBA", 300, 108, 104))
        with self.assertRaisesRegex(ValueError, "mixed-provider"):
            report(self.path)

    def test_whitespace_provider_fixture_identity_rejected(self):
        ledger = PredictionLedger(self.path)
        ledger.record_prediction(PredictionRecord("fixture-1", "NBA", 100, 110, 100, 0.7))
        ledger.record_fixture_start("NBA", "fixture-1", 200)
        ledger.record_fixture_provenance("NBA", "fixture-1", "ESPN", "espn-1", 200)
        ledger.record_outcome(OutcomeRecord("fixture-1", "NBA", 300, 108, 104))
        with ledger._connect() as db:
            db.execute("UPDATE fixture_provenance SET provider_fixture_id='   '")
        with self.assertRaises(ValueError):
            report(self.path)

    def test_blank_provider_name_refused(self):
        ledger = PredictionLedger(self.path)
        ledger.record_prediction(PredictionRecord("fixture-1", "NBA", 100, 110, 100, 0.7))
        ledger.record_fixture_start("NBA", "fixture-1", 200)
        ledger.record_fixture_provenance("NBA", "fixture-1", "ESPN", "espn-1", 200)
        ledger.record_outcome(OutcomeRecord("fixture-1", "NBA", 300, 108, 104))
        with ledger._connect() as db:
            db.execute("UPDATE fixture_provenance SET provider='   '")
        with self.assertRaises(ValueError):
            report(self.path)

    def test_corrupt_result_timestamp_before_tipoff_excluded(self):
        ledger = PredictionLedger(self.path)
        ledger.record_prediction(PredictionRecord("fixture-1", "NBA", 100, 110, 100, 0.7))
        ledger.record_fixture_start("NBA", "fixture-1", 200)
        ledger.record_fixture_provenance("NBA", "fixture-1", "ESPN", "espn-1", 200)
        ledger.record_outcome(OutcomeRecord("fixture-1", "NBA", 300, 108, 104))
        with ledger._connect() as db:
            db.execute("UPDATE outcomes SET result_ts_utc=200")
        result = report(self.path)
        self.assertEqual(result["status"], "no_verified_pairs")
        self.assertEqual(result["audit"]["provider_consistent_prematch_pairs"], 0)
        self.assertEqual(result["audit"]["primary_exclusion_reasons"]["fixture_start_not_before_result"], 1)

    def test_corrupt_prediction_timestamp_at_tipoff_excluded(self):
        ledger = PredictionLedger(self.path)
        ledger.record_prediction(PredictionRecord("fixture-1", "NBA", 100, 110, 100, 0.7))
        ledger.record_fixture_start("NBA", "fixture-1", 200)
        ledger.record_fixture_provenance("NBA", "fixture-1", "ESPN", "espn-1", 200)
        ledger.record_outcome(OutcomeRecord("fixture-1", "NBA", 300, 108, 104))
        with ledger._connect() as db:
            db.execute("UPDATE predictions SET prediction_ts_utc=200")
        result = report(self.path)
        self.assertEqual(result["status"], "no_verified_pairs")
        self.assertEqual(result["audit"]["provider_consistent_prematch_pairs"], 0)
        self.assertEqual(result["audit"]["primary_exclusion_reasons"]["prediction_not_before_tipoff"], 1)

    def test_prediction_equal_result_timestamp_excluded(self):
        ledger = PredictionLedger(self.path)
        ledger.record_prediction(PredictionRecord("fixture-1", "NBA", 100, 110, 100, 0.7))
        ledger.record_fixture_start("NBA", "fixture-1", 200)
        ledger.record_fixture_provenance("NBA", "fixture-1", "ESPN", "espn-1", 200)
        ledger.record_outcome(OutcomeRecord("fixture-1", "NBA", 300, 108, 104))
        with ledger._connect() as db:
            db.execute("UPDATE predictions SET prediction_ts_utc=300")
        result = report(self.path)
        self.assertEqual(result["status"], "no_verified_pairs")
        self.assertEqual(result["audit"]["provider_consistent_prematch_pairs"], 0)
        self.assertEqual(result["audit"]["primary_exclusion_reasons"]["prediction_not_before_result"], 1)

    def test_prediction_result_scope_mismatch_excluded(self):
        ledger = PredictionLedger(self.path)
        ledger.record_prediction(PredictionRecord("fixture-1", "NBA", 100, 110, 100, 0.7))
        ledger.record_fixture_start("NBA", "fixture-1", 200)
        ledger.record_fixture_provenance("NBA", "fixture-1", "ESPN", "espn-1", 200)
        ledger.record_outcome(OutcomeRecord(
            "fixture-1", "NBA", 300, 108, 104, scope="REGULATION_ONLY"
        ))
        result = report(self.path)
        self.assertEqual(result["status"], "no_verified_pairs")
        self.assertEqual(result["audit"]["provider_consistent_prematch_pairs"], 0)
        self.assertEqual(result["audit"]["primary_exclusion_reasons"]["prediction_result_scope_mismatch"], 1)

    def test_overlapping_exclusions_count_one_primary_reason(self):
        ledger = PredictionLedger(self.path)
        ledger.record_prediction(PredictionRecord("fixture-1", "NBA", 250, 110, 100, 0.7))
        ledger.record_fixture_start("NBA", "fixture-1", 200)
        ledger.record_fixture_provenance("NBA", "fixture-1", "ESPN", "espn-1", 201)
        ledger.record_outcome(OutcomeRecord(
            "fixture-1", "NBA", 300, 108, 104, scope="REGULATION_ONLY"
        ))
        result = report(self.path)
        audit = result["audit"]
        self.assertEqual(result["status"], "no_verified_pairs")
        self.assertTrue(audit["exclusion_reason_counts_overlap"])
        self.assertEqual(audit["excluded_matched_pairs"], 1)
        self.assertEqual(audit["scope_mismatch_pairs"], 1)
        self.assertEqual(audit["provider_start_conflicts"], 1)
        self.assertEqual(audit["primary_exclusion_reasons"]["prediction_result_scope_mismatch"], 1)
        self.assertEqual(sum(audit["primary_exclusion_reasons"].values()), 1)

    def test_multiple_fixtures_primary_exclusions_reconcile(self):
        ledger = PredictionLedger(self.path)
        for fixture, prediction_ts, result_scope in (
            ("late", 210, "FINAL_WITH_OT"),
            ("scope", 100, "REGULATION_ONLY"),
            ("valid", 100, "FINAL_WITH_OT"),
        ):
            ledger.record_prediction(PredictionRecord(fixture, "NBA", prediction_ts, 110, 100, 0.7))
            ledger.record_fixture_start("NBA", fixture, 200)
            ledger.record_fixture_provenance("NBA", fixture, "ESPN", fixture, 200)
            ledger.record_outcome(OutcomeRecord(fixture, "NBA", 300, 108, 104, scope=result_scope))
        result = report(self.path)
        audit = result["audit"]
        self.assertEqual(result["status"], "evaluated")
        self.assertEqual(result["metrics"]["n_games"], 1)
        self.assertEqual(audit["matched"], 3)
        self.assertEqual(audit["excluded_matched_pairs"], 2)
        self.assertEqual(audit["primary_exclusion_reasons"]["prediction_not_before_tipoff"], 1)
        self.assertEqual(audit["primary_exclusion_reasons"]["prediction_result_scope_mismatch"], 1)
        self.assertEqual(sum(audit["primary_exclusion_reasons"].values()), 2)

    def test_missing_provider_fixture_excluded_without_affecting_valid_metrics(self):
        ledger = PredictionLedger(self.path)
        for fixture in ("valid", "missing"):
            ledger.record_prediction(PredictionRecord(fixture, "NBA", 100, 110, 100, 0.7))
            ledger.record_fixture_start("NBA", fixture, 200)
            ledger.record_outcome(OutcomeRecord(fixture, "NBA", 300, 108, 104))
        ledger.record_fixture_provenance("NBA", "valid", "ESPN", "espn-valid", 200)
        result = report(self.path)
        self.assertEqual(result["status"], "evaluated")
        self.assertEqual(result["metrics"]["n_games"], 1)
        self.assertAlmostEqual(result["metrics"]["total_mae"], 2.0)
        self.assertEqual(result["audit"]["excluded_matched_pairs"], 1)
        self.assertEqual(result["audit"]["primary_exclusion_reasons"]["missing_provider_identity"], 1)

    def test_provider_start_conflict_excluded_without_changing_valid_mae(self):
        ledger = PredictionLedger(self.path)
        for fixture in ("valid", "conflict"):
            ledger.record_prediction(PredictionRecord(fixture, "NBA", 100, 110, 100, 0.7))
            ledger.record_fixture_start("NBA", fixture, 200)
            ledger.record_outcome(OutcomeRecord(fixture, "NBA", 300, 108, 104))
        ledger.record_fixture_provenance("NBA", "valid", "ESPN", "espn-valid", 200)
        ledger.record_fixture_provenance("NBA", "conflict", "ESPN", "espn-conflict", 201)
        result = report(self.path)
        self.assertEqual(result["status"], "evaluated")
        self.assertEqual(result["metrics"]["n_games"], 1)
        self.assertAlmostEqual(result["metrics"]["total_mae"], 2.0)
        self.assertEqual(result["audit"]["excluded_matched_pairs"], 1)
        self.assertEqual(result["audit"]["primary_exclusion_reasons"]["provider_fixture_start_conflict"], 1)

    def test_whitespace_provider_name_classified_as_missing_identity(self):
        ledger = PredictionLedger(self.path)
        ledger.record_prediction(PredictionRecord("fixture-1", "NBA", 100, 110, 100, 0.7))
        ledger.record_fixture_start("NBA", "fixture-1", 200)
        ledger.record_fixture_provenance("NBA", "fixture-1", "ESPN", "espn-1", 200)
        ledger.record_outcome(OutcomeRecord("fixture-1", "NBA", 300, 108, 104))
        with ledger._connect() as db:
            db.execute("UPDATE fixture_provenance SET provider='   '")
        with self.assertRaisesRegex(ValueError, "mixed-provider"):
            report(self.path)
        audit = ledger.audit_provenance("NBA")
        self.assertEqual(audit["provider_consistent_prematch_pairs"], 0)
        self.assertEqual(audit["missing_provider_identity"], 1)

    def test_mixed_espn_and_other_provider_refuses_entire_report(self):
        ledger = PredictionLedger(self.path)
        for fixture, provider in (("espn", "ESPN"), ("other", "OTHER")):
            ledger.record_prediction(PredictionRecord(fixture, "NBA", 100, 110, 100, 0.7))
            ledger.record_fixture_start("NBA", fixture, 200)
            ledger.record_fixture_provenance("NBA", fixture, provider, fixture, 200)
            ledger.record_outcome(OutcomeRecord(fixture, "NBA", 300, 108, 104))
        with self.assertRaisesRegex(ValueError, "mixed-provider"):
            report(self.path)

    def test_invalid_foreign_provider_does_not_block_valid_espn_sample(self):
        ledger = PredictionLedger(self.path)
        for fixture, provider, prediction_ts in (
            ("espn", "ESPN", 100),
            ("foreign-late", "OTHER", 210),
        ):
            ledger.record_prediction(PredictionRecord(fixture, "NBA", prediction_ts, 110, 100, 0.7))
            ledger.record_fixture_start("NBA", fixture, 200)
            ledger.record_fixture_provenance("NBA", fixture, provider, fixture, 200)
            ledger.record_outcome(OutcomeRecord(fixture, "NBA", 300, 108, 104))
        result = report(self.path)
        self.assertEqual(result["status"], "evaluated")
        self.assertEqual(result["metrics"]["n_games"], 1)
        self.assertAlmostEqual(result["metrics"]["total_mae"], 2.0)
        self.assertEqual(result["audit"]["excluded_matched_pairs"], 1)
        self.assertEqual(result["audit"]["primary_exclusion_reasons"]["prediction_not_before_tipoff"], 1)

    def test_other_league_foreign_provider_does_not_contaminate_nba(self):
        ledger = PredictionLedger(self.path)
        for league, fixture, provider in (
            ("NBA", "nba-game", "ESPN"),
            ("EuroLeague", "euro-game", "OTHER"),
        ):
            ledger.record_prediction(PredictionRecord(fixture, league, 100, 110, 100, 0.7))
            ledger.record_fixture_start(league, fixture, 200)
            ledger.record_fixture_provenance(league, fixture, provider, fixture, 200)
            ledger.record_outcome(OutcomeRecord(fixture, league, 300, 108, 104))
        result = report(self.path, league="NBA")
        self.assertEqual(result["status"], "evaluated")
        self.assertEqual(result["metrics"]["n_games"], 1)
        self.assertEqual(result["audit"]["matched"], 1)
        self.assertEqual(result["audit"]["excluded_matched_pairs"], 0)

    def test_uncertainty_uses_same_valid_sample_as_mae(self):
        ledger = PredictionLedger(self.path)
        for fixture, predicted_total, actual_home, actual_away, start in (
            ("valid-a", 210, 108, 104, 200),
            ("valid-b", 230, 106, 104, 200),
            ("invalid", 999, 106, 104, 201),
        ):
            ledger.record_prediction(PredictionRecord(fixture, "NBA", 100, predicted_total / 2, predicted_total / 2, 0.7))
            ledger.record_fixture_start("NBA", fixture, 200)
            ledger.record_fixture_provenance("NBA", fixture, "ESPN", fixture, start)
            ledger.record_outcome(OutcomeRecord(fixture, "NBA", 300, actual_home, actual_away))
        result = report(self.path)
        self.assertEqual(result["metrics"]["n_games"], 2)
        self.assertAlmostEqual(result["metrics"]["total_mae"], 11.0)
        self.assertEqual(result["audit"]["excluded_matched_pairs"], 1)
        self.assertIsNotNone(result["uncertainty"]["total_mae"])

    def test_tied_final_score_is_rejected_by_verified_metrics(self):
        ledger = PredictionLedger(self.path)
        ledger.record_prediction(PredictionRecord("tied-final", "NBA", 100, 110, 100, 0.7))
        ledger.record_fixture_start("NBA", "tied-final", 200)
        ledger.record_fixture_provenance("NBA", "tied-final", "ESPN", "espn-tied", 200)
        ledger.record_outcome(OutcomeRecord("tied-final", "NBA", 300, 105, 105))
        with self.assertRaisesRegex(ValueError, "decisive result"):
            report(self.path)

    def test_missing_provenance_excluded(self):
        ledger = PredictionLedger(self.path)
        ledger.record_prediction(PredictionRecord("fixture-1", "NBA", 100, 110, 100, 0.7))
        ledger.record_fixture_start("NBA", "fixture-1", 200)
        ledger.record_outcome(OutcomeRecord("fixture-1", "NBA", 300, 108, 104))
        self.assertEqual(report(self.path)["status"], "no_verified_pairs")


if __name__ == "__main__":
    unittest.main()
