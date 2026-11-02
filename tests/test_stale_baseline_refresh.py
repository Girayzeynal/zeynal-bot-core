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
