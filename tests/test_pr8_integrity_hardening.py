"""Regression tests for PR #8 data-integrity hardening."""
import asyncio
import tempfile
import time
import unittest

from baseline.team_baseline_store import TeamBaseline, TeamBaselineBootstrapper, TeamBaselineStore


class EmptyProvider:
    async def fetch_team_recent_games(self, league, team, n_games):
        return []


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
