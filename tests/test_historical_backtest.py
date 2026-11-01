import unittest

from historical_backtest import HistoricalPrediction, evaluate_predictions


def game(**changes):
    fields = dict(
        fixture_id="game-1", league="NBA", prediction_ts_utc=100,
        result_ts_utc=200, expected_home=110.0, expected_away=100.0,
        actual_home=112, actual_away=98, home_win_probability=0.8,
    )
    fields.update(changes)
    return HistoricalPrediction(**fields)


class HistoricalBacktestTests(unittest.TestCase):
    def test_metrics_from_known_game(self):
        result = evaluate_predictions([game()])
        self.assertEqual(result.n_games, 1)
        self.assertAlmostEqual(result.score_mae, 2)
        self.assertAlmostEqual(result.score_rmse, 2)
        self.assertAlmostEqual(result.total_mae, 0)
        self.assertAlmostEqual(result.home_win_brier, 0.04)
        self.assertAlmostEqual(result.home_win_log_loss, 0.2231435513)

    def test_signed_bias_identifies_over_and_under_prediction(self):
        first = game(expected_home=120.0, expected_away=105.0)
        second = game(
            fixture_id="game-2", expected_home=100.0, expected_away=95.0,
            actual_home=110, actual_away=100,
        )
        metrics = evaluate_predictions([first, second])
        self.assertAlmostEqual(metrics.home_score_bias, -1.0)
        self.assertAlmostEqual(metrics.away_score_bias, 1.0)
        self.assertAlmostEqual(metrics.total_bias, 0.0)

    def test_prediction_after_tipoff_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_predictions([game(fixture_start_ts_utc=90)])
        with self.assertRaises(ValueError):
            evaluate_predictions([game(fixture_start_ts_utc=200)])

    def test_future_leakage_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_predictions([game(prediction_ts_utc=200)])

    def test_duplicate_fixture_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_predictions([game(), game()])

    def test_regulation_vs_overtime_scope_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_predictions([game(prediction_scope="REGULATION_ONLY")])

    def test_probability_outside_unit_interval_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_predictions([game(home_win_probability=1.1)])

    def test_missing_probability_does_not_fabricate_metric(self):
        result = evaluate_predictions([game(home_win_probability=None)])
        self.assertIsNone(result.home_win_brier)
        self.assertIsNone(result.home_win_log_loss)
        self.assertEqual(result.n_probability_games, 0)

    def test_empty_dataset_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_predictions([])


if __name__ == "__main__":
    unittest.main()
