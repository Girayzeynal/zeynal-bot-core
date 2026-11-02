"""Regression tests for PR #8 data-integrity hardening."""
import asyncio
import tempfile
import time
import unittest

from baseline.team_baseline_store import TeamBaseline, TeamBaselineBootstrapper, TeamBaselineStore


class EmptyProvider:
    async def fetch_team_recent_games(self, league, team, n_games):
        return []

class DuplicateProvider:
    def __init__(self, game):
        self.game = game

    async def fetch_team_recent_games(self, league, team, n_games):
        return [self.game]


class IntegrityHardeningTests(unittest.TestCase):
    def test_anonymous_same_timestamp_distinct_games_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            ts = int(time.time()) - 86400
            store.append_game("NBA", "BOS", 110, 100, 98.0, True, ts_utc=ts)
            store.append_game("NBA", "BOS", 111, 100, 98.0, True, ts_utc=ts)
            self.assertEqual(len(store.get_series("NBA", "BOS", 20)), 2)
            store.append_game("NBA", "BOS", 110, 100, 98.0, True, ts_utc=ts)
            self.assertEqual(len(store.get_series("NBA", "BOS", 20)), 2)

    def test_duplicate_provider_does_not_restamp_stale_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            ts = int(time.time()) - 86400 * 10
            game = {"pts_for": 110, "pts_against": 100, "pace": 98.0,
                    "home": True, "ts_utc": ts, "game_id": "000001",
                    "source": "test", "timestamp_precision": "exact"}
            store.append_game("NBA", "BOS", 110, 100, 98.0, True,
                              ts_utc=ts, game_id="000001", source="test",
                              timestamp_precision="exact")
            for i in range(1, 6):
                store.append_game("NBA", "BOS", 100 + i, 95, 98.0,
                                  True, ts_utc=ts + i)
            old_ts = int(time.time()) - 86400 * 9
            store.put(TeamBaseline("NBA", "BOS", 6, 102.5, 95.0, 98.0, 0.0, old_ts))
            result = asyncio.run(TeamBaselineBootstrapper(
                store, [DuplicateProvider(game)]
            ).ensure_async("NBA", "BOS", min_games=6))
            self.assertIsNone(result)
            self.assertEqual(store.get("NBA", "BOS").updated_ts, old_ts)

    def test_recent_cache_does_not_skip_provider_check(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            ts = int(time.time()) - 86400 * 10
            for i in range(6):
                store.append_game("NBA", "BOS", 100 + i, 95, 98.0,
                                  True, ts_utc=ts + i)
            cached_ts = int(time.time()) - 3600
            store.put(TeamBaseline("NBA", "BOS", 6, 102.5, 95.0, 98.0, 0.0, cached_ts))
            result = asyncio.run(TeamBaselineBootstrapper(
                store, [EmptyProvider()]
            ).ensure_async("NBA", "BOS", min_games=6))
            self.assertIsNone(result)
            self.assertEqual(store.get("NBA", "BOS").updated_ts, cached_ts)

    def test_newer_game_refreshes_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            ts = int(time.time()) - 86400 * 10
            for i in range(6):
                store.append_game("NBA", "BOS", 100 + i, 95, 98.0,
                                  True, ts_utc=ts + i)
            old_ts = int(time.time()) - 86400 * 9
            store.put(TeamBaseline("NBA", "BOS", 6, 102.5, 95.0, 98.0, 0.0, old_ts))
            game = {"pts_for": 120, "pts_against": 105, "pace": 99.0,
                    "home": True, "ts_utc": ts + 86400, "game_id": "000002",
                    "source": "test", "timestamp_precision": "exact"}
            result = asyncio.run(TeamBaselineBootstrapper(
                store, [DuplicateProvider(game)]
            ).ensure_async("NBA", "BOS", min_games=6))
            self.assertIsNotNone(result)
            self.assertEqual(result.n_games, 6)
            self.assertGreater(result.updated_ts, old_ts)
            self.assertEqual(len(store.get_series("NBA", "BOS", 20)), 7)

    def test_undersampled_newer_game_does_not_publish_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            ts = int(time.time()) - 86400 * 10
            for i in range(4):
                store.append_game("NBA", "BOS", 100 + i, 95, 98.0,
                                  True, ts_utc=ts + i)
            game = {"pts_for": 120, "pts_against": 105, "pace": 99.0,
                    "home": True, "ts_utc": ts + 86400, "game_id": "000003",
                    "source": "test", "timestamp_precision": "exact"}
            result = asyncio.run(TeamBaselineBootstrapper(
                store, [DuplicateProvider(game)]
            ).ensure_async("NBA", "BOS", min_games=6))
            self.assertIsNone(result)
            self.assertIsNone(store.get("NBA", "BOS"))
            self.assertEqual(len(store.get_series("NBA", "BOS", 20)), 5)

    def test_missing_measured_pace_does_not_publish_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            ts = int(time.time()) - 86400 * 10
            game = {"pts_for": 120, "pts_against": 105, "pace": None,
                    "home": True, "ts_utc": ts, "game_id": "000004",
                    "source": "nba_com", "timestamp_precision": "date_only"}
            result = asyncio.run(TeamBaselineBootstrapper(
                store, [DuplicateProvider(game)]
            ).ensure_async("NBA", "BOS", min_games=6))
            self.assertIsNone(result)
            self.assertEqual(store.get_series("NBA", "BOS", 20), [])
            self.assertIsNone(store.get("NBA", "BOS"))

    def test_empty_provider_does_not_restamp_stale_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            ts = int(time.time()) - 86400 * 10
            for i in range(6):
                store.append_game("NBA", "BOS", 100 + i, 95, 98.0, True, ts_utc=ts + i)
            old_ts = int(time.time()) - 86400 * 9
            store.put(TeamBaseline("NBA", "BOS", 6, 102.5, 95.0, 98.0, 0.0, old_ts))
            result = asyncio.run(TeamBaselineBootstrapper(store, [EmptyProvider()]).ensure_async("NBA", "BOS", min_games=6))
            self.assertIsNone(result)
            self.assertEqual(store.get("NBA", "BOS").updated_ts, old_ts)


if __name__ == "__main__":
    unittest.main()
