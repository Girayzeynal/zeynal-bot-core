"""The canonical adapter must never invent pace from final scores."""
import tempfile
import unittest
from unittest.mock import AsyncMock

from baseline.team_baseline_store import TeamBaselineBootstrapper, TeamBaselineStore
from providers.espn_adapter import ESPNAdapter
from providers.espn_boxscore_pace import METHOD
from test_espn_boxscore_pace import fixture, game


class RecentPaceTests(unittest.IsolatedAsyncioTestCase):
    def adapter(self, *, opt_in=False):
        adapter = ESPNAdapter(allow_estimated_pace=opt_in)
        adapter.resolve_team = AsyncMock(return_value={"id": "19", "abbr": "ORL"})
        adapter.fetch_completed_nba_events = AsyncMock(return_value=[game(fixture())])
        adapter._get_json = AsyncMock(return_value=fixture())
        return adapter

    async def test_default_is_score_only_and_preserves_provider_identity(self):
        adapter = self.adapter()
        rows = await adapter.fetch_team_recent_games("NBA", "ORL", 6)
        self.assertIsNone(rows[0]["pace"])
        self.assertEqual(rows[0]["game_id"], "401909903")
        self.assertEqual(rows[0]["source"], "ESPN_SCOREBOARD")
        self.assertEqual(rows[0]["timestamp_precision"], "exact")
        self.assertTrue(rows[0]["home"])
        adapter._get_json.assert_not_awaited()

    async def test_estimate_is_explicit_and_has_auditable_inputs(self):
        rows = await self.adapter(opt_in=True).fetch_team_recent_games("NBA", "ORL", 6)
        self.assertAlmostEqual(rows[0]["pace"], 94.4)
        self.assertEqual(rows[0]["source"], METHOD)
        self.assertEqual(rows[0]["pace_kind"], "BOX_SCORE_ESTIMATE")
        self.assertEqual(rows[0]["pace_evidence"]["inputs"]["home"]["total_turnovers"], 18)
        self.assertEqual((rows[0]["pts_for"], rows[0]["pts_against"]), (97, 108))

    async def test_missing_summary_keeps_pace_unavailable_even_with_opt_in(self):
        adapter = self.adapter(opt_in=True)
        adapter._get_json.return_value = None
        rows = await adapter.fetch_team_recent_games("NBA", "ORL", 6)
        self.assertIsNone(rows[0]["pace"])
        self.assertEqual(rows[0]["pace_kind"], "UNAVAILABLE")

    async def test_default_score_only_data_cannot_enter_baseline_store(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            result = await TeamBaselineBootstrapper(store, [self.adapter()]).ensure_async(
                "NBA", "ORL", min_games=1)
            self.assertIsNone(result)
            self.assertEqual(store.get_series("NBA", "ORL", 100), [])

    async def test_invalid_limit_and_implicit_opt_in_are_rejected(self):
        for flag in (1, "true", None):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                ESPNAdapter(allow_estimated_pace=flag)
        for count in (True, 0, 101, 1.5):
            with self.subTest(count=count), self.assertRaises(ValueError):
                await self.adapter().fetch_team_recent_games("NBA", "ORL", count)


if __name__ == "__main__":
    unittest.main()
