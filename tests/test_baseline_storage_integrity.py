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

    def test_failed_atomic_write_removes_unique_temp_file(self):
        import os
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            store = TeamBaselineStore(folder)
            ts = int(time.time()) - 86400
            store.append_game("NBA", "BOS", 110, 100, 98, True, ts_utc=ts)
            before = set(os.listdir(store.series_dir))
            with patch("baseline.team_baseline_store.os.replace",
                       side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    store.append_game("NBA", "BOS", 115, 102, 99, True, ts_utc=ts + 60)
            self.assertEqual(set(os.listdir(store.series_dir)), before)
            self.assertEqual(len(store.get_series("NBA", "BOS", 20)), 1)

    def test_historical_cutoff_rejects_invalid_types_and_excludes_future(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TeamBaselineStore(folder)
            ts = int(time.time()) - 86400
            store.append_game("NBA", "BOS", 110, 100, 98, True, ts_utc=ts, timestamp_precision="exact")
            store.append_game("NBA", "BOS", 115, 105, 99, False, ts_utc=ts + 60, timestamp_precision="exact")
            for cutoff in (None, 0, -1, True, float(ts), str(ts)):
                with self.subTest(cutoff=cutoff):
                    self.assertEqual(store.get_series_before("NBA", "BOS", cutoff, 10), [])
            for count in (0, -1, True, 2.0, "2"):
                with self.subTest(count=count):
                    self.assertEqual(store.get_series_before("NBA", "BOS", ts + 120, count), [])
            records = store.get_series_before("NBA", "BOS", ts + 60, 10)
            self.assertEqual([r.ts_utc for r in records], [ts])

    def test_invalid_baseline_sample_sizes_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TeamBaselineStore(folder)
            ts = int(time.time()) - 86400
            for i in range(6):
                store.append_game("NBA", "BOS", 110 + i, 100 + i, 98,
                                  i % 2 == 0, ts_utc=ts - i * 86400, timestamp_precision="exact")
            for count, minimum in ((0, 0), (6, 0), (6, -1), (2, 3),
                                   (6, True), (6, 2.0), ("6", 3)):
                with self.subTest(count=count, minimum=minimum):
                    self.assertIsNone(store.compute_baseline_before(
                        "NBA", "BOS", ts + 60, n_games=count, min_games=minimum))
            for count in (0, -1, True, "6", 6.0):
                with self.subTest(dynamic_count=count):
                    self.assertIsNone(store.compute_dynamic_baseline("NBA", "BOS", count))
            self.assertEqual(store.compute_baseline_before(
                "NBA", "BOS", ts + 60, n_games=6, min_games=6)["n_games"], 6)

    def test_historical_backtest_excludes_unknown_and_date_only(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TeamBaselineStore(folder)
            ts = int(time.time()) - 86400 * 5
            store.append_game("NBA", "BOS", 101, 90, 98, True, ts_utc=ts,
                              game_id="a", source="fixture", timestamp_precision="date_only")
            store.append_game("NBA", "BOS", 102, 91, 98, True, ts_utc=ts + 1,
                              game_id="b", source="fixture")
            store.append_game("NBA", "BOS", 103, 92, 98, True, ts_utc=ts + 2,
                              game_id="c", source="fixture", timestamp_precision="exact")
            rows = store.get_series_before("NBA", "BOS", ts + 100, 10)
            self.assertEqual([r.game_id for r in rows], ["c"])
            self.assertIsNone(store.compute_baseline_before(
                "NBA", "BOS", ts + 100, n_games=3, min_games=2))
            for bad_precision in ("approximate", None, 1, False, []):
                with self.subTest(bad_precision=bad_precision):
                    with self.assertRaises(ValueError):
                        store.append_game("NBA", "BOS", 104, 93, 98, True,
                                          ts_utc=ts + 3,
                                          timestamp_precision=bad_precision)

    def test_nba_com_date_only_cannot_be_upgraded_to_exact(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TeamBaselineStore(folder)
            ts = int(time.time()) - 86400 * 5
            with self.assertRaises(ValueError):
                store.append_game("NBA", "BOS", 110, 100, 98, True,
                                  ts_utc=ts, game_id="123", source="nba_com",
                                  timestamp_precision="exact")
            store.append_game("NBA", "BOS", 110, 100, 98, True,
                              ts_utc=ts, game_id="123", source="nba_com",
                              timestamp_precision="date_only")
            self.assertEqual(store.get_series_before("NBA", "BOS", ts + 86400, 10), [])
            self.assertEqual(len(store.get_series("NBA", "BOS", 10)), 1)

    def test_provider_identity_rejects_control_and_padding(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TeamBaselineStore(folder)
            ts = int(time.time()) - 86400
            for source, game_id in (("nba_com ", "123"), ("nba_com", " 123"),
                                    ("nba_com", "123" + chr(10)),
                                    ("nba" + chr(0) + "_com", "123")):
                with self.subTest(source=source, game_id=game_id):
                    with self.assertRaises(ValueError):
                        store.append_game("NBA", "BOS", 110, 100, 98, True,
                                          ts_utc=ts, game_id=game_id, source=source)
            self.assertEqual(store.get_series("NBA", "BOS", 10), [])

    def test_duplicate_persisted_provider_identity_blocks_mutation(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            store = TeamBaselineStore(folder)
            ts = int(time.time()) - 86400
            store.append_game("NBA", "BOS", 110, 100, 98, True,
                              ts_utc=ts, game_id="123", source="fixture")
            path = store._series_path("NBA", "BOS")
            with open(path, "r", encoding="utf-8") as handle:
                existing = json.load(handle)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(existing + existing, handle)
            with self.assertRaisesRegex(ValueError, "duplicate persisted"):
                store.append_game("NBA", "BOS", 115, 102, 99, False,
                                  ts_utc=ts + 60, game_id="456", source="fixture")
            with open(path, "r", encoding="utf-8") as handle:
                self.assertEqual(len(json.load(handle)), 2)

    def test_malformed_persisted_row_blocks_mutation(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            store = TeamBaselineStore(folder)
            ts = int(time.time()) - 86400
            store.append_game("NBA", "BOS", 110, 100, 98, True,
                              ts_utc=ts, game_id="123", source="fixture")
            path = store._series_path("NBA", "BOS")
            with open(path, "r", encoding="utf-8") as handle:
                existing = json.load(handle)
            malformed = existing + [{"unexpected": "record"}]
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(malformed, handle)
            with self.assertRaisesRegex(ValueError, "invalid persisted game record"):
                store.append_game("NBA", "BOS", 115, 102, 99, False,
                                  ts_utc=ts + 60, game_id="456", source="fixture")
            with open(path, "r", encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), malformed)

    def test_versioned_identity_keys_prevent_aliases_and_preserve_legacy(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TeamBaselineStore(folder)
            self.assertEqual(store._key("NBA", "BOS"), "NBA__BOS")
            pairs = (("NBA__EAST", "BOS"), ("NBA", "EAST__BOS"),
                     ("NBA", "BOS__A"), ("NBA", "A B"),
                     ("NBA", "A_B"), ("EuroLeague", "Fenerbahçe"),
                     ("EuroLeague", "FENERBAHCE"))
            keys = [store._key(league, team) for league, team in pairs]
            self.assertEqual(len(keys), len(set(keys)))
            self.assertTrue(store._key("EuroLeague", "Fenerbahçe").startswith("V2_"))
            self.assertEqual(store._key("EuroLeague", "fenerbahçe"),
                             store._key("EuroLeague", "FENERBAHÇE"))
            for bad in ("../BOS", "BOS/OTHER", "BOS\\\\OTHER", "BOS" + chr(10) + "OTHER", "BOS" + chr(0xD800)):
                with self.subTest(bad=bad):
                    with self.assertRaises(ValueError):
                        store._key("NBA", bad)

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
