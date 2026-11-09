import math
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from verified_nba_accuracy import verified_nba_accuracy


class VerifiedNbaAccuracyTests(unittest.TestCase):
    def test_empty_and_unverified_are_not_reported_as_accuracy(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "ledger.sqlite")
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE predictions (league TEXT, fixture_id TEXT)")
                db.execute("INSERT INTO predictions VALUES ('NBA', 'a')")
                db.execute("INSERT INTO predictions VALUES ('NBA', 'b')")
            with patch("verified_nba_accuracy.compare_fixture", side_effect=lambda path, fid: {
                "status": "UNVERIFIED_FINAL" if fid == "a" else "NO_PREMATCH_PREDICTION"
            }):
                result = verified_nba_accuracy(path)
            self.assertEqual(result["verified"], 0)
            self.assertIsNone(result["total_mae"])
            self.assertIsNone(result["total_bias"])
            self.assertIsNone(result["total_rmse"])
            self.assertEqual(result["excluded"]["UNVERIFIED_FINAL"], 1)

    def test_invalid_verified_metrics_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "ledger.sqlite")
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE predictions (league TEXT, fixture_id TEXT)")
                db.execute("INSERT INTO predictions VALUES ('NBA', 'bad')")
            for invalid in (float("nan"), float("inf"), True, "10"):
                with self.subTest(invalid=repr(invalid)):
                    with patch("verified_nba_accuracy.compare_fixture",
                               return_value={"status": "EVALUATED",
                                             "signed_errors": {"total": invalid, "margin": 1},
                                             "winner_direction_correct": True}):
                        with self.assertRaises(ValueError):
                            verified_nba_accuracy(path)
            with patch("verified_nba_accuracy.compare_fixture",
                       return_value={"status": "EVALUATED",
                                     "signed_errors": {"total": 1, "margin": 1},
                                     "winner_direction_correct": "yes"}):
                with self.assertRaises(ValueError):
                    verified_nba_accuracy(path)

    def test_only_verified_pairs_enter_error_denominator(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "ledger.sqlite")
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE predictions (league TEXT, fixture_id TEXT)")
                db.executemany("INSERT INTO predictions VALUES ('NBA', ?)", [
                    ("a",), ("b",), ("c",)])
            def compare(_, fid):
                if fid == "c":
                    return {"status": "UNVERIFIED_FINAL"}
                return {"status": "EVALUATED",
                        "signed_errors": {"total": 10 if fid == "a" else -4,
                                          "margin": 2 if fid == "a" else -6},
                        "winner_direction_correct": fid == "a"}
            with patch("verified_nba_accuracy.compare_fixture", side_effect=compare):
                result = verified_nba_accuracy(path)
            self.assertEqual(result["status"], "LOW_VERIFIED_SAMPLE")
            self.assertEqual(result["verified"], 2)
            self.assertEqual(result["total_mae"], 7)
            self.assertEqual(result["margin_mae"], 4)
            self.assertEqual(result["total_bias"], 3)
            self.assertEqual(result["margin_bias"], -2)
            self.assertAlmostEqual(result["total_rmse"], math.sqrt(58))
            self.assertAlmostEqual(result["margin_rmse"], math.sqrt(20))
            self.assertEqual(result["winner_accuracy"], 0.5)
            self.assertEqual(result["winner_sample"], 2)
            self.assertEqual(result["calibration"], "NOT_VERIFIED")
            with patch("verified_nba_accuracy.compare_fixture", side_effect=compare):
                sufficient = verified_nba_accuracy(path, minimum_sample=2)
            self.assertEqual(sufficient["status"], "EVALUATED")


if __name__ == "__main__":
    unittest.main()
