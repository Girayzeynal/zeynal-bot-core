"""Regression: missing possessions must never be stored as synthetic pace."""
import asyncio
import tempfile
import unittest

from baseline.team_baseline_store import TeamBaselineBootstrapper, TeamBaselineStore


class FakeAdapter:
    async def fetch_team_recent_games(self, league, team, n_games):
        return [
            {"ts_utc": 1000000000 + i * 86400, "pts_for": 105,
             "pts_against": 99, "pace": pace, "home": True}
            for i, pace in enumerate((None, 0, float("nan"), "invalid", 97.5))
        ]


class MissingPaceRegressionTests(unittest.TestCase):
    def test_bootstrapper_does_not_store_missing_or_invalid_pace(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TeamBaselineStore(folder)
            result = asyncio.run(
                TeamBaselineBootstrapper(store, [FakeAdapter()]).ensure_async(
                    "NBA", "BOS", min_games=6
                )
            )
            self.assertIsNone(result)
            series = store.get_series("NBA", "BOS", 50)
            self.assertEqual(len(series), 1)
            self.assertEqual(series[0].pace, 97.5)


if __name__ == "__main__":
    unittest.main()
