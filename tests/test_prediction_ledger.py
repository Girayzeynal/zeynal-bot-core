import os
import tempfile
import unittest

from prediction_ledger import PredictionLedger, PredictionRecord, OutcomeRecord


class PredictionLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = PredictionLedger(os.path.join(self.tmp.name, "ledger.sqlite"))

    def tearDown(self):
        self.tmp.cleanup()

    def prediction(self, **kwargs):
        data = dict(fixture_id="fixture-1", league="NBA",
                    prediction_ts_utc=100, expected_home=110.0,
                    expected_away=100.0, home_win_probability=0.8)
        data.update(kwargs)
        return PredictionRecord(**data)

    def outcome(self, **kwargs):
        data = dict(fixture_id="fixture-1", league="NBA",
                    result_ts_utc=200, actual_home=112, actual_away=98)
        data.update(kwargs)
        return OutcomeRecord(**data)

    def test_idempotent_prediction_and_outcome(self):
        self.assertTrue(self.ledger.record_prediction(self.prediction()))
        self.assertFalse(self.ledger.record_prediction(self.prediction(expected_home=999)))
        self.assertTrue(self.ledger.record_outcome(self.outcome()))
        self.assertFalse(self.ledger.record_outcome(self.outcome(actual_home=10)))
        metrics = self.ledger.evaluate()
        self.assertEqual(metrics.n_games, 1)
        self.assertAlmostEqual(metrics.score_mae, 2.0)

    def test_unmatched_outcome_is_not_evaluated(self):
        self.ledger.record_outcome(self.outcome())
        with self.assertRaises(ValueError):
            self.ledger.evaluate()

    def test_prediction_after_result_is_rejected_on_evaluation(self):
        self.ledger.record_prediction(self.prediction(prediction_ts_utc=300))
        self.ledger.record_outcome(self.outcome())
        with self.assertRaises(ValueError):
            self.ledger.evaluate()

    def test_scope_mismatch_is_rejected(self):
        self.ledger.record_prediction(self.prediction(scope="REGULATION_ONLY"))
        self.ledger.record_outcome(self.outcome())
        with self.assertRaises(ValueError):
            self.ledger.evaluate()

    def test_league_isolation(self):
        self.ledger.record_prediction(self.prediction())
        self.ledger.record_outcome(self.outcome())
        self.ledger.record_prediction(self.prediction(league="EuroLeague"))
        self.ledger.record_outcome(self.outcome(league="EuroLeague"))
        self.assertEqual(self.ledger.evaluate("NBA").n_games, 1)
        self.assertEqual(self.ledger.evaluate("EuroLeague").n_games, 1)

    def test_audit_counts_unmatched_and_invalid_pairs(self):
        self.ledger.record_prediction(self.prediction())
        self.ledger.record_outcome(self.outcome())
        self.ledger.record_prediction(
            self.prediction(fixture_id="unmatched-prediction")
        )
        self.ledger.record_outcome(
            self.outcome(fixture_id="unmatched-outcome")
        )
        self.ledger.record_prediction(
            self.prediction(fixture_id="late", prediction_ts_utc=300)
        )
        self.ledger.record_outcome(self.outcome(fixture_id="late"))
        audit = self.ledger.audit("NBA")
        self.assertEqual(audit["predictions"], 3)
        self.assertEqual(audit["outcomes"], 3)
        self.assertEqual(audit["matched"], 2)
        self.assertEqual(audit["eligible_pairs"], 1)
        self.assertEqual(audit["unmatched_predictions"], 1)
        self.assertEqual(audit["unmatched_outcomes"], 1)
        self.assertEqual(audit["invalid_time_pairs"], 1)
        self.assertEqual(audit["scope_mismatch_pairs"], 0)

    def test_prematch_audit_requires_fixture_start(self):
        self.ledger.record_prediction(self.prediction())
        self.ledger.record_outcome(self.outcome())
        missing = self.ledger.audit_prematch("NBA")
        self.assertEqual(missing["missing_fixture_start"], 1)
        self.assertEqual(missing["valid_prematch_pairs"], 0)
        self.assertTrue(self.ledger.record_fixture_start("NBA", "fixture-1", 150))
        self.assertFalse(self.ledger.record_fixture_start("NBA", "fixture-1", 160))
        valid = self.ledger.audit_prematch("NBA")
        self.assertEqual(valid["valid_prematch_pairs"], 1)
        self.assertEqual(valid["missing_fixture_start"], 0)

    def test_in_game_prediction_not_counted_as_prematch(self):
        self.ledger.record_prediction(self.prediction(prediction_ts_utc=175))
        self.ledger.record_outcome(self.outcome())
        self.ledger.record_fixture_start("NBA", "fixture-1", 150)
        self.assertEqual(self.ledger.audit_prematch("NBA")["valid_prematch_pairs"], 0)

    def test_evaluate_prematch_excludes_in_game_and_missing_tipoff(self):
        self.ledger.record_prediction(self.prediction())
        self.ledger.record_outcome(self.outcome())
        self.ledger.record_fixture_start("NBA", "fixture-1", 150)
        self.ledger.record_prediction(
            self.prediction(fixture_id="late", prediction_ts_utc=175)
        )
        self.ledger.record_outcome(self.outcome(fixture_id="late"))
        self.ledger.record_fixture_start("NBA", "late", 150)
        self.ledger.record_prediction(self.prediction(fixture_id="missing"))
        self.ledger.record_outcome(self.outcome(fixture_id="missing"))
        result = self.ledger.evaluate_prematch("NBA")
        self.assertEqual(result.n_games, 1)
        self.assertAlmostEqual(result.score_mae, 2.0)

    def test_evaluate_prematch_requires_eligible_records(self):
        self.ledger.record_prediction(self.prediction())
        self.ledger.record_outcome(self.outcome())
        with self.assertRaises(ValueError):
            self.ledger.evaluate_prematch("NBA")

    def test_provider_provenance_detects_tipoff_conflict(self):
        self.ledger.record_prediction(self.prediction())
        self.ledger.record_outcome(self.outcome())
        self.ledger.record_fixture_start("NBA", "fixture-1", 150)
        self.assertTrue(self.ledger.record_fixture_provenance(
            "NBA", "fixture-1", "ESPN", "espn-123", 160
        ))
        self.assertFalse(self.ledger.record_fixture_provenance(
            "NBA", "fixture-1", "ESPN", "espn-123", 150
        ))
        audit = self.ledger.audit_provenance("NBA")
        self.assertEqual(audit["provider_start_conflicts"], 1)
        self.assertEqual(audit["provider_consistent_prematch_pairs"], 0)

    def test_provider_provenance_requires_unique_source_fixture(self):
        self.assertTrue(self.ledger.record_fixture_provenance(
            "NBA", "fixture-1", "ESPN", "espn-123", 150
        ))
        self.assertFalse(self.ledger.record_fixture_provenance(
            "NBA", "fixture-2", "ESPN", "espn-123", 150
        ))

    def test_verified_evaluation_rejects_provenance_conflict(self):
        self.ledger.record_prediction(self.prediction())
        self.ledger.record_outcome(self.outcome())
        self.ledger.record_fixture_start("NBA", "fixture-1", 150)
        self.ledger.record_fixture_provenance("NBA", "fixture-1", "ESPN", "123", 160)
        with self.assertRaises(ValueError):
            self.ledger.evaluate_provenance_verified("NBA")

    def test_verified_evaluation_uses_only_consistent_fixture(self):
        self.ledger.record_prediction(self.prediction())
        self.ledger.record_outcome(self.outcome())
        self.ledger.record_fixture_start("NBA", "fixture-1", 150)
        self.ledger.record_fixture_provenance("NBA", "fixture-1", "ESPN", "123", 150)
        self.ledger.record_prediction(self.prediction(fixture_id="other"))
        self.ledger.record_outcome(self.outcome(fixture_id="other"))
        self.ledger.record_fixture_start("NBA", "other", 150)
        self.ledger.record_fixture_provenance("NBA", "other", "ESPN", "124", 160)
        metrics = self.ledger.evaluate_provenance_verified("NBA")
        self.assertEqual(metrics.n_games, 1)
        self.assertAlmostEqual(metrics.score_mae, 2.0)

    def test_nonnumeric_and_boolean_projection_values_rejected(self):
        for value in (True, False, "110", None, [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.ledger.record_prediction(self.prediction(expected_home=value))
            if value is not None:
                with self.subTest(probability=value), self.assertRaises(ValueError):
                    self.ledger.record_prediction(self.prediction(home_win_probability=value))
        self.assertEqual(self.ledger.audit("NBA")["predictions"], 0)
        # None explicitly represents unavailable calibration, not malformed input.
        self.assertTrue(self.ledger.record_prediction(
            self.prediction(home_win_probability=None)))

    def test_invalid_probability_rejected(self):
        with self.assertRaises(ValueError):
            self.ledger.record_prediction(self.prediction(home_win_probability=float("nan")))


if __name__ == "__main__":
    unittest.main()
