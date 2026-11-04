"""Synthetic score/error cases validate interpretation, not actual accuracy."""
from dataclasses import replace
import unittest
from historical_backtest import HistoricalPrediction
from bound_error_uncertainty import describe_error_uncertainty


def game(index, herror=2, aerror=-2):
    return HistoricalPrediction(str(index), "NBA", index*10+1, index*10+9,
                                100+herror, 90+aerror, 100, 90,
                                fixture_start_ts_utc=index*10+5)


class BoundErrorUncertaintyTests(unittest.TestCase):
    def test_empty_and_singleton_samples_have_no_intervals(self):
        for rows in ([], [game(1)]):
            report = describe_error_uncertainty(rows)
            self.assertEqual(report["status"], "insufficient_verified_sample")
            for item in report["intervals"].values():
                self.assertIsNone(item["iid"])
                self.assertIsNone(item["chronological_block"])

    def test_team_errors_are_resampled_as_whole_games(self):
        report = describe_error_uncertainty([game(1), game(2)])
        for key, value in (("total_bias", 0), ("total_mae", 0), ("score_mae", 2)):
            interval = report["intervals"][key]["iid"]
            self.assertEqual(interval["n"], 2)
            self.assertEqual(interval["estimate"], value)
            self.assertEqual(interval["lower"], value)
            self.assertEqual(interval["upper"], value)
        self.assertEqual(report["resampling_unit"], "whole_game")

    def test_small_sample_has_no_block_interval(self):
        report = describe_error_uncertainty([game(i) for i in range(1,10)])
        self.assertIsNone(report["intervals"]["total_bias"]["chronological_block"])
        self.assertEqual(report["calibration_status"], "NOT_ESTABLISHED")

    def test_order_and_repeated_runs_are_deterministic(self):
        rows = [game(i, i, i%3) for i in range(1,11)]
        first = describe_error_uncertainty(rows)
        self.assertEqual(first, describe_error_uncertainty(list(reversed(rows))))
        block = first["intervals"]["total_bias"]["chronological_block"]
        self.assertEqual(block["n"], 10)
        self.assertEqual(block["block_size"], 5)
        self.assertEqual(block["method"], "circular_moving_block_bootstrap")

    def test_mixed_league_scope_missing_start_and_duplicates_rejected(self):
        for rows in ([game(1), game(1)], [replace(game(1), fixture_start_ts_utc=None)],
                     [game(1), replace(game(2), league="EUROLEAGUE")],
                     [game(1), replace(game(2), prediction_scope="REGULATION_ONLY", result_scope="REGULATION_ONLY")]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                describe_error_uncertainty(rows)
