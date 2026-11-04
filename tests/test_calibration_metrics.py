"""Calibration metrics contract tests: only verified pregame predictions count."""
import math
import unittest

from calibration_metrics import evaluate_verified_totals


def snap(key, ts, expected, quality="VERIFIED_BASELINE"):
    date, home, away, league = key.split(":")
    return {"fixture_key": key, "ts": ts, "payload": {
        "ctx": {"date": date, "home": home, "away": away, "league": league},
        "meta": {"expected_total": expected, "data_quality": quality}}}


def final(start, home, away):
    return {"start_utc": start, "home_score": home, "away_score": away,
            "status": "FINAL", "verified": True}


class CalibrationMetricsTests(unittest.TestCase):
    def test_verified_two_match_mae_rmse_bias(self):
        snapshots = [snap("2026-11-04:a:Away:NBA", 100, 200), snap("2026-11-04:b:Away:NBA", 100, 210)]
        results = {"2026-11-04:a:Away:NBA": final(200, 100, 90), "2026-11-04:b:Away:NBA": final(200, 110, 110)}
        report = evaluate_verified_totals(snapshots, results)
        self.assertEqual(report["sample_size"], 2)
        self.assertEqual(report["mae"], 10)
        self.assertEqual(report["rmse"], 10)
        self.assertEqual(report["bias"], 0)

    def test_excludes_unverified_post_tipoff_duplicate_and_invalid(self):
        snapshots = [
            snap("2026-11-04:a:Away:NBA", 200, 200),  # at tipoff
            snap("2026-11-04:b:Away:NBA", 100, 200),  # unverified result
            snap("2026-11-04:c:Away:NBA", 100, float("nan")),
            snap("2026-11-04:d:Away:NBA", 100, 200),  # invalid score
            snap("2026-11-04:e:Away:NBA", 100, 200),  # valid
            snap("2026-11-04:e:Away:NBA", 100, 250),  # duplicate
        ]
        results = {
            "2026-11-04:a:Away:NBA": final(200, 100, 100),
            "2026-11-04:b:Away:NBA": {**final(200, 100, 100), "verified": False},
            "2026-11-04:c:Away:NBA": final(200, 100, 100),
            "2026-11-04:d:Away:NBA": final(200, -1, 100),
            "2026-11-04:e:Away:NBA": final(200, 100, 100),
        }
        report = evaluate_verified_totals(snapshots, results)
        self.assertEqual(report["sample_size"], 1)
        self.assertEqual(report["mae"], 0)
        self.assertEqual(report["excluded"], {
            "duplicate": 1, "unverified_result": 1, "invalid_prediction": 1,
            "invalid_score": 1, "not_prematch": 1, "unverified_baseline": 0,
            "identity_mismatch": 0,
        })

    def test_manual_baseline_is_excluded_from_verified_accuracy(self):
        snapshots = [snap("2026-11-04:manual:Away:NBA", 100, 200, "MANUAL_BASELINE"),
                     snap("2026-11-04:verified:Away:NBA", 100, 205)]
        results = {"2026-11-04:manual:Away:NBA": final(200, 100, 100),
                   "2026-11-04:verified:Away:NBA": final(200, 100, 100)}
        report = evaluate_verified_totals(snapshots, results)
        self.assertEqual(report["sample_size"], 1)
        self.assertEqual(report["mae"], 5)
        self.assertEqual(report["excluded"]["unverified_baseline"], 1)

    def test_mismatched_snapshot_context_is_excluded(self):
        key = "2026-11-04:Home:Away:NBA"
        record = snap(key, 100, 200)
        record["payload"]["ctx"]["home"] = "Wrong"
        report = evaluate_verified_totals([record], {key: final(200, 100, 100)})
        self.assertEqual(report["sample_size"], 0)
        self.assertEqual(report["excluded"]["identity_mismatch"], 1)

    def test_no_verified_data_does_not_claim_accuracy(self):
        report = evaluate_verified_totals([], {})
        self.assertEqual(report["status"], "INSUFFICIENT_VERIFIED_DATA")
        self.assertIsNone(report["mae"])
        self.assertIsNone(report["rmse"])
        self.assertIsNone(report["bias"])


if __name__ == "__main__":
    unittest.main()
