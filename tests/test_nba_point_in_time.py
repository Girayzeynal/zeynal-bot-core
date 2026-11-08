import asyncio
import tempfile
import unittest
from datetime import datetime, timezone

from baseline.team_baseline_store import TeamBaselineStore, TeamBaseline
from faz13_engine import Faz13Engine, PrematchRequest


class PointInTimeTests(unittest.TestCase):
    def test_future_games_never_enter_prematch_average(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            cutoff = int(datetime(2026, 11, 9, tzinfo=timezone.utc).timestamp())
            for team, pf, pa in (("DET", 100, 90), ("LAL", 110, 105)):
                for i in range(6):
                    store.append_game("NBA", team, pf + (-1 if i % 2 else 1), pa, 99, True,
                                      ts_utc=cutoff - (i + 1) * 86400)
                store.append_game("NBA", team, 190, 190, 99, True,
                                  ts_utc=cutoff + 86400)
                store.put(TeamBaseline("NBA", team, 7, 170, 170, 99, 5, cutoff))
            engine = Faz13Engine("test", "https://example.invalid", baseline_store=store)
            engine.espn = None
            result = asyncio.run(engine.run_prematch(
                PrematchRequest(0, "NBA", "2026-11-09", "DET", "LAL", True)))
            self.assertEqual(result.home_avg.points_for, 100)
            self.assertEqual(result.away_avg.points_for, 110)
            self.assertEqual(result.meta["home_baseline_games"], 6)
            self.assertEqual(result.meta["away_baseline_games"], 6)
            self.assertTrue(result.meta["point_in_time"])
            self.assertEqual(result.meta["simulation"]["n"], 10000)
            self.assertIn("Monte Carlo: 10000 senaryo", result.render_html())
            self.assertIn("48 dk sonunda eşitlik", result.render_html())
            self.assertNotIn("40 dk", result.render_html())
            self.assertIn("kesin skor değil", result.render_html())
            self.assertAlmostEqual(sum(result.meta["simulation"][k] for k in ("home_win_pct", "away_win_pct", "tie_pct")), 100, places=6)
            self.assertIn("PRE_FIXTURE_SERIES", result.meta["home_sources"])

    def test_exact_tipoff_includes_same_utc_day_pre_game_record(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            cutoff = int(datetime(2026, 11, 9, 4, tzinfo=timezone.utc).timestamp())
            for team in ("DET", "LAL"):
                for i in range(5):
                    store.append_game("NBA", team, 100 + (i % 2), 90, 99, True,
                                      ts_utc=cutoff - (i + 1) * 86400)
                store.append_game("NBA", team, 105, 95, 99, True,
                                  ts_utc=cutoff - 3600)
                store.append_game("NBA", team, 200, 190, 99, True,
                                  ts_utc=cutoff + 3600)
                store.put(TeamBaseline("NBA", team, 7, 160, 150, 99, 5, cutoff))
            engine = Faz13Engine("test", "https://example.invalid", baseline_store=store)
            engine.espn = None
            result = asyncio.run(engine.run_prematch(
                PrematchRequest(0, "NBA", "2026-11-09", "DET", "LAL", True, cutoff)))
            self.assertAlmostEqual(result.home_avg.points_for, 100 + 2 / 6 + 5 / 6)
            self.assertEqual(result.meta["home_baseline_games"], 6)
            self.assertIn("04:00:00+00:00", result.meta["cutoff_utc"])

    def test_insufficient_historical_games_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            cutoff = int(datetime(2026, 11, 9, tzinfo=timezone.utc).timestamp())
            for team in ("DET", "LAL"):
                for i in range(5):
                    store.append_game("NBA", team, 105, 101, 99, True,
                                      ts_utc=cutoff - (i + 1) * 86400)
                store.put(TeamBaseline("NBA", team, 10, 115, 110, 99, 5, cutoff))
            engine = Faz13Engine("test", "https://example.invalid", baseline_store=store)
            engine.espn = None
            with self.assertRaisesRegex(ValueError, "Point-in-time sample insufficient"):
                asyncio.run(engine.run_prematch(
                    PrematchRequest(0, "NBA", "2026-11-09", "DET", "LAL", True)))


if __name__ == "__main__":
    unittest.main()
