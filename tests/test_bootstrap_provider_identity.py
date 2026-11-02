"""Provider identity and boolean home flag are preserved during baseline bootstrap."""
import asyncio
import tempfile
import time
import unittest

from baseline.team_baseline_store import TeamBaselineBootstrapper, TeamBaselineStore


class FakeAdapter:
    def __init__(self, home=True):
        self.home = home

    async def fetch_team_recent_games(self, league, team, n_games):
        now = int(time.time())
        return [
            {"ts_utc": now - (i + 1) * 86400, "pts_for": 100 + i,
             "pts_against": 90 + i, "pace": 98.0, "home": self.home,
             "game_id": f"g{i}", "source": "verified_test_provider"}
            for i in range(6)
        ]


class BootstrapProvenanceTests(unittest.TestCase):
    def test_bootstrap_retains_provider_game_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            result = asyncio.run(TeamBaselineBootstrapper(
                store, [FakeAdapter()]).ensure_async("NBA", "BOS", min_games=6))
            self.assertIsNotNone(result)
            records = store.get_series("NBA", "BOS", 20)
            self.assertEqual(len(records), 6)
            self.assertEqual({r.source for r in records}, {"verified_test_provider"})
            self.assertEqual({r.game_id for r in records},
                             {f"g{i}" for i in range(6)})

    def test_bootstrap_rejects_non_boolean_home_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            result = asyncio.run(TeamBaselineBootstrapper(
                store, [FakeAdapter(home="false")]).ensure_async(
                    "NBA", "BOS", min_games=6))
            self.assertIsNone(result)
            self.assertEqual(store.get_series("NBA", "BOS", 20), [])
