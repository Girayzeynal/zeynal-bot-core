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

    def test_invalid_probability_rejected(self):
        with self.assertRaises(ValueError):
            self.ledger.record_prediction(self.prediction(home_win_probability=float("nan")))


if __name__ == "__main__":
    unittest.main()
