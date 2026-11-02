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

    def test_distinct_game_ids_at_same_timestamp_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TeamBaselineStore(folder)
            ts = int(time.time()) - 86400
            store.append_game("NBA", "BOS", 110, 100, 98, True, ts_utc=ts, game_id="001", source="provider_a")
            store.append_game("NBA", "BOS", 115, 105, 99, False, ts_utc=ts, game_id="002", source="provider_a")
            self.assertEqual(len(store.get_series("NBA", "BOS", 20)), 2)
            store.append_game("NBA", "BOS", 110, 100, 98, True, ts_utc=ts, game_id="001", source="provider_a")
            with self.assertRaises(ValueError):
                store.append_game("NBA", "BOS", 112, 101, 98, True, ts_utc=ts, game_id="001", source="provider_a")
            records = store.get_series("NBA", "BOS", 20)
            self.assertEqual(len(records), 2)
            self.assertEqual(next(r.pts_for for r in records if r.game_id == "001"), 110)

    def test_game_id_requires_source(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TeamBaselineStore(folder)
            with self.assertRaises(ValueError):
                store.append_game("NBA", "BOS", 110, 100, 98, True,
                                  ts_utc=int(time.time()) - 86400, game_id="001")

    def test_corrupt_existing_history_is_not_overwritten(self):
        import os
        with tempfile.TemporaryDirectory() as folder:
            store = TeamBaselineStore(folder)
            path = store._series_path("NBA", "BOS")
            corrupt = "{broken json"
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(corrupt)
            with self.assertRaises(ValueError):
                store.append_game("NBA", "BOS", 110, 100, 98, True,
                                  ts_utc=int(time.time()) - 86400)
            with open(path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), corrupt)

    def test_rejects_path_traversal_in_team_and_league(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TeamBaselineStore(folder)
            for league, team in [
                ("NBA", "../escape"),
                ("../escape", "BOS"),
                ("NBA", "BOS/../../escape"),
                ("NBA", "BOS\\\\escape"),
                ("NBA", ""),
            ]:
                with self.subTest(league=league, team=team):
                    with self.assertRaises(ValueError):
                        store.get(league, team)
            self.assertTrue(store._series_path("NBA", "BOS").startswith(folder))

    def test_rejects_coerced_statistics_and_invalid_limits(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TeamBaselineStore(folder)
            ts = int(time.time()) - 86400
            for pf, pa, pace, home, limit in [
                ("110", 100, 98, True, 20),
                (True, 100, 98, True, 20),
                (110, "100", 98, True, 20),
                (110, 100, "98", True, 20),
                (110, 100, 98, 1, 20),
                (110, 100, 98, True, 0),
                (110, 100, 98, True, -1),
            ]:
                with self.subTest(pf=pf, pa=pa, pace=pace, home=home, limit=limit):
                    with self.assertRaises(ValueError):
                        store.append_game("NBA", "BOS", pf, pa, pace, home,
                                          ts_utc=ts, max_games=limit)
            self.assertEqual(store.get_series("NBA", "BOS", 20), [])

    def test_zero_and_negative_requested_games_never_return_full_history(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TeamBaselineStore(folder)
            store.append_game("NBA", "BOS", 110, 100, 98, True,
                              ts_utc=int(time.time()) - 86400)
            self.assertEqual(store.get_series("NBA", "BOS", 0), [])
            self.assertEqual(store.get_series("NBA", "BOS", -1), [])
            self.assertEqual(len(store.get_series("NBA", "BOS", 1)), 1)

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
