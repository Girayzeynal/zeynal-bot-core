"""A stale baseline must not masquerade as a successful refresh."""
import asyncio
import tempfile
import time
import unittest

from baseline.team_baseline_store import TeamBaseline, TeamBaselineBootstrapper, TeamBaselineStore


class NoGamesAdapter:
    async def fetch_team_recent_games(self, league, team, n_games):
        return None


class StaleBaselineTests(unittest.TestCase):
    def test_fresh_reconciled_baseline_survives_duplicate_only_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            now = int(time.time())
            for i in range(6):
                store.append_game("NBA", "BOS", 110.0 + i, 100.0 + i,
                                  98.0 + i, True, ts_utc=now - (7 - i) * 3600,
                                  game_id=str(1000 + i), source="TEST_FIXTURE",
                                  timestamp_precision="exact")
            aggregate = store.compute_dynamic_baseline("NBA", "BOS", 6)
            self.assertIsNotNone(aggregate)
            baseline = TeamBaseline("NBA", "BOS", 6, aggregate["pts_for"],
                                    aggregate["pts_against"], aggregate["pace"],
                                    aggregate["stdev_total"], now)
            store.put(baseline)
            result = asyncio.run(TeamBaselineBootstrapper(store, [NoGamesAdapter()]).ensure_async("NBA", "BOS"))
            self.assertEqual(result, baseline)

    def test_fresh_baseline_without_reconciled_history_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            store.put(TeamBaseline("NBA", "BOS", 6, 110, 100, 99, 8, int(time.time())))
            result = asyncio.run(TeamBaselineBootstrapper(store, [NoGamesAdapter()]).ensure_async("NBA", "BOS"))
            self.assertIsNone(result)

    def test_stale_baseline_is_not_returned_on_failed_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            store.put(TeamBaseline("NBA", "BOS", 10, 110, 100, 99, 8, int(time.time()) - 9 * 86400))
            result = asyncio.run(TeamBaselineBootstrapper(store, [NoGamesAdapter()]).ensure_async("NBA", "BOS"))
            self.assertIsNone(result)

    def test_undersampled_baseline_is_not_returned_on_failed_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            store.put(TeamBaseline("NBA", "BOS", 2, 110, 100, 99, 8, int(time.time())))
            result = asyncio.run(TeamBaselineBootstrapper(store, [NoGamesAdapter()]).ensure_async("NBA", "BOS"))
            self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
