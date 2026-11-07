"""Synthetic chronology tests; no real accuracy claims."""
import unittest
from dataclasses import replace
from historical_backtest import HistoricalPrediction
from walk_forward_calibration import evaluate_walk_forward


def game(key, predicted, start, observed, home=110, away=90):
    return HistoricalPrediction(key, "NBA", predicted, observed, home, away, 100, 90,
                                fixture_start_ts_utc=start)


class WalkForwardTests(unittest.TestCase):
    def test_bias_learned_only_from_prior_observations(self):
        rows = [game("a", 10, 20, 30), game("b", 40, 50, 60), game("c", 70, 80, 90)]
        report = evaluate_walk_forward(rows, 2)
        self.assertEqual(report["evaluated_games"], 1)
        self.assertEqual(report["insufficient_training_games"], 2)
        self.assertEqual(report["original_metrics"]["total_mae"], 10)
        self.assertEqual(report["corrected_metrics"]["total_mae"], 0)
        self.assertEqual(report["folds"][0]["latest_training_result_ts_utc"], 60)
        self.assertEqual(report["calibration_status"], "NOT_ESTABLISHED")

    def test_late_observed_and_equal_timestamp_results_excluded(self):
        rows = [game("a", 10, 20, 70), game("b", 40, 50, 60), game("c", 70, 80, 90)]
        report = evaluate_walk_forward(rows, 1)
        self.assertEqual(report["evaluated_games"], 1)
        self.assertEqual(report["folds"][0]["training_games"], 1)
        self.assertEqual(report["folds"][0]["home_bias"], 10)

    def test_future_results_cannot_change_earlier_fold(self):
        rows = [game("a", 10, 20, 30), game("b", 40, 50, 60)]
        first = evaluate_walk_forward(rows, 1)["folds"][0]
        extended = rows + [game("c", 70, 80, 90, home=999)]
        self.assertEqual(evaluate_walk_forward(extended, 1)["folds"][0], first)
        self.assertEqual(evaluate_walk_forward(list(reversed(extended)), 1),
                         evaluate_walk_forward(extended, 1))

    def test_empty_sample_has_no_metrics(self):
        report = evaluate_walk_forward([])
        self.assertEqual(report["status"], "insufficient_verified_history")
        self.assertIsNone(report["corrected_metrics"])
        self.assertEqual(report["evaluated_games"], 0)

    def test_reject_duplicate_mixed_league_scope_and_missing_start(self):
        row = game("a", 10, 20, 30)
        for rows in ([row, row], [replace(row, fixture_start_ts_utc=None)],
                     [row, replace(game("b", 40, 50, 60), league="EUROLEAGUE")],
                     [row, replace(game("b", 40, 50, 60), prediction_scope="REGULATION", result_scope="REGULATION")]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                evaluate_walk_forward(rows, 1)

    def test_invalid_correction_is_not_clipped(self):
        rows = [game("a", 10, 20, 30, home=300), game("b", 40, 50, 60, home=10)]
        report = evaluate_walk_forward(rows, 1)
        self.assertEqual(report["invalid_corrections"], 1)
        self.assertEqual(report["evaluated_games"], 0)
        self.assertIsNone(report["corrected_metrics"])

    def test_training_threshold_validation(self):
        for value in (True, 0, -1, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                evaluate_walk_forward([], value)
