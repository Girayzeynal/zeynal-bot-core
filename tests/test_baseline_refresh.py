import tempfile
import time
import unittest
from unittest.mock import AsyncMock

from baseline.team_baseline_store import TeamBaseline, TeamBaselineBootstrapper, TeamBaselineStore


class BaselineRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_baseline_is_refetched(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TeamBaselineStore(base_dir=folder)
            store.put(TeamBaseline("NBA", "SAS", 6, 110.0, 105.0, 100.0, 12.0, int(time.time()) - 9 * 86400))
            adapter = type("Adapter", (), {})()
            adapter.fetch_team_recent_games = AsyncMock(return_value=[
                {"ts_utc": int(time.time()) - (i + 1) * 86400,
                 "pts_for": 115.0, "pts_against": 108.0, "pace": 100.0, "home": bool(i % 2)}
                for i in range(6)
            ])
            result = await TeamBaselineBootstrapper(store, [adapter]).ensure_async("NBA", "SAS", 6)
            adapter.fetch_team_recent_games.assert_awaited_once()
            self.assertEqual(result.n_games, 6)
            self.assertLess(time.time() - result.updated_ts, 60)

    async def test_fresh_baseline_avoids_refetch(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TeamBaselineStore(base_dir=folder)
            store.put(TeamBaseline("NBA", "UTA", 6, 110.0, 105.0, 100.0, 12.0, int(time.time())))
            adapter = type("Adapter", (), {})()
            adapter.fetch_team_recent_games = AsyncMock()
            result = await TeamBaselineBootstrapper(store, [adapter]).ensure_async("NBA", "UTA", 6)
            self.assertEqual(result.team, "UTA")
            adapter.fetch_team_recent_games.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
