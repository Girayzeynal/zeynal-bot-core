"""Malformed observations must never become descriptive accuracy metrics."""
import unittest
from historical_backtest import evaluate_predictions
from tests.test_historical_backtest import game


class BacktestInputValidationTests(unittest.TestCase):
    def test_boolean_and_string_magnitudes_rejected(self):
        for field in ("expected_home", "expected_away", "home_win_probability"):
            for value in (True, False, "1", None if field != "home_win_probability" else "0.5"):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    evaluate_predictions([game(**{field: value})])

    def test_timestamps_require_positive_non_boolean_integers(self):
        for field in ("prediction_ts_utc", "result_ts_utc", "fixture_start_ts_utc"):
            for value in (True, False, 0, -1, 1.5, "150", float("nan")):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    evaluate_predictions([game(**{field: value})])

    def test_actual_scores_must_be_non_boolean_integers(self):
        for field in ("actual_home", "actual_away"):
            for value in (True, False, 100.0, "100", None):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    evaluate_predictions([game(**{field: value})])

    def test_malformed_and_untrimmed_identities_rejected(self):
        for field in ("league", "fixture_id"):
            for value in (None, 1, "", " ", " NBA", "NBA "):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    evaluate_predictions([game(**{field: value})])

    def test_matching_but_unknown_scopes_rejected(self):
        for value in (None, "", "FINAL", "REGULATION", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                evaluate_predictions([game(prediction_scope=value, result_scope=value)])

    def test_supported_scope_and_zero_actual_score_remain_valid(self):
        for scope in ("REGULATION_ONLY", "FINAL_WITH_OT"):
            metrics = evaluate_predictions([game(actual_away=0, prediction_scope=scope, result_scope=scope)])
            self.assertEqual(metrics.n_games, 1)

    def test_non_record_rejected_with_validation_error(self):
        for value in (None, {}, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                evaluate_predictions([value])
