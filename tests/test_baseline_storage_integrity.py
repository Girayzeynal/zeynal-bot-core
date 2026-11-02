"""Storage-level fail-closed historical record regressions."""
import tempfile
import time
import unittest

from baseline.team_baseline_store import TeamBaselineStore


class BaselineStorageIntegrityTests(unittest.TestCase):
    def test_rejects_missing_future_and_invalid_history(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TeamBaselineStore(folder)
            now = int(time.time())
            for ts, pf, pa, pace in [
                (None, 105, 99, 99),
                (0, 105, 99, 99),
                (now + 3600, 105, 99, 99),
                (now - 86400, 105, 99, None),
                (now - 86400, 105, 99, float("nan")),
                (now - 86400, -1, 99, 99),
            ]:
                with self.subTest(ts=ts, pace=pace, pf=pf):
                    with self.assertRaises((ValueError, TypeError)):
                        store.append_game("NBA", "BOS", pf, pa, pace, True, ts_utc=ts)
            self.assertEqual(store.get_series("NBA", "BOS", 20), [])

    def test_series_write_is_atomic_when_serialization_fails(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            store = TeamBaselineStore(folder)
            ts = int(time.time()) - 86400
            store.append_game("NBA", "BOS", 110, 100, 98.5, True, ts_utc=ts)
            with patch("baseline.team_baseline_store.json.dump", side_effect=OSError("disk write failed")):
                with self.assertRaises(OSError):
                    store.append_game("NBA", "BOS", 115, 102, 99, True, ts_utc=ts + 60)
            records = store.get_series("NBA", "BOS", 20)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].ts_utc, ts)

    def test_valid_record_is_stored(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TeamBaselineStore(folder)
            ts = int(time.time()) - 86400
            store.append_game("NBA", "BOS", 110, 100, 98.5, True, ts_utc=ts)
            games = store.get_series("NBA", "BOS", 20)
            self.assertEqual(len(games), 1)
            self.assertEqual(games[0].ts_utc, ts)
            self.assertEqual(games[0].pace, 98.5)


if __name__ == "__main__":
    unittest.main()
