import os
import tempfile
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from prediction_ledger import PredictionLedger
from providers.espn_adapter import ESPNAdapter
from nba_prematch_orchestrator import persist_resolved_nba_prematch


class NbaPrematchOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ledger = PredictionLedger(os.path.join(tmp.name, "ledger.sqlite"))
        self.adapter = ESPNAdapter()
        self.series_store = SimpleNamespace(
            get_series=lambda league, team, count: [
                SimpleNamespace(ts_utc=self.tipoff - 1000 - i,
                                game_id=f"game-{i}", source="ESPN",
                                timestamp_precision="exact",
                                pts_for=110.0, pts_against=105.0, pace=99.0)
                for i in range(6)
            ])
        self.adapter.resolve_team = AsyncMock(side_effect=[
            {"id": "1"}, {"id": "2"}])
        self.tipoff = int(datetime(2026, 11, 4, 1, 30, tzinfo=timezone.utc).timestamp())
        self.adapter.fetch_scheduled_nba_scoreboard_date = AsyncMock(
            return_value=[dict(provider="ESPN", provider_fixture_id="espn-1",
                               home_team_id="1", away_team_id="2",
                               start_ts_utc=self.tipoff)])
        self.core = SimpleNamespace(
            ctx=SimpleNamespace(league="NBA", date="2026-11-04",
                                home="Home", away="Away"),
            meta=dict(data_quality="VERIFIED_BASELINE",
                      generated_at=self.tipoff - 120,
                      expected_home=110.0, expected_away=105.0,
                      expected_total=215.0,
                      home_sources=["TEAM_BASELINE_STORE"], away_sources=["TEAM_BASELINE_STORE"],
                      home_baseline_key="Home", away_baseline_key="Away",
                      home_baseline_games=6, away_baseline_games=6),
            home_avg=SimpleNamespace(points_for=110.0, points_against=105.0, pace=99.0),
            away_avg=SimpleNamespace(points_for=110.0, points_against=105.0, pace=99.0))

    async def test_numerical_mismatch_rejected_without_write(self):
        self.core.home_avg.points_for = 112.0
        with self.assertRaisesRegex(ValueError, "points_for"):
            await persist_resolved_nba_prematch(
                adapter=self.adapter, ledger=self.ledger, core=self.core,
                baseline_store=self.series_store,
                observed_at_utc=self.tipoff - 60)
        with self.ledger._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM predictions").fetchone()[0], 0)

    async def test_baseline_sample_count_mismatch_rejected(self):
        self.core.meta["home_baseline_games"] = 7
        with self.assertRaisesRegex(ValueError, "sample count"):
            await persist_resolved_nba_prematch(
                adapter=self.adapter, ledger=self.ledger, core=self.core,
                baseline_store=self.series_store,
                observed_at_utc=self.tipoff - 60)

    async def test_wrong_baseline_binding_rejected_without_write(self):
        self.core.meta["home_baseline_key"] = "Other"
        with self.assertRaisesRegex(ValueError, "baseline key binding"):
            await persist_resolved_nba_prematch(
                adapter=self.adapter, ledger=self.ledger, core=self.core,
                baseline_store=self.series_store,
                observed_at_utc=self.tipoff - 60)
        with self.ledger._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM predictions").fetchone()[0], 0)

    async def test_unbound_source_rejected(self):
        self.core.meta["away_sources"] = ["ESPN_LAST5"]
        with self.assertRaisesRegex(ValueError, "Unbound away"):
            await persist_resolved_nba_prematch(
                adapter=self.adapter, ledger=self.ledger, core=self.core,
                baseline_store=self.series_store,
                observed_at_utc=self.tipoff - 60)

    async def test_missing_series_store_rejected(self):
        with self.assertRaisesRegex(ValueError, "historical game series"):
            await persist_resolved_nba_prematch(
                adapter=self.adapter, ledger=self.ledger, core=self.core,
                observed_at_utc=self.tipoff - 60)

    async def test_post_prediction_series_rejected_without_write(self):
        self.series_store.get_series = lambda league, team, count: [
            SimpleNamespace(ts_utc=self.tipoff - 10 + i,
                            game_id=f"late-{i}", source="ESPN",
                            timestamp_precision="exact")
            for i in range(6)
        ]
        with self.assertRaisesRegex(ValueError, "Insufficient pre-prediction"):
            await persist_resolved_nba_prematch(
                adapter=self.adapter, ledger=self.ledger, core=self.core,
                baseline_store=self.series_store,
                observed_at_utc=self.tipoff - 60)
        with self.ledger._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM predictions").fetchone()[0], 0)

    async def test_valid_identity_persists(self):
        result = await persist_resolved_nba_prematch(
            adapter=self.adapter, ledger=self.ledger, core=self.core,
            baseline_store=self.series_store,
                observed_at_utc=self.tipoff - 60)
        self.assertTrue(result["inserted"])
        self.assertEqual(result["fixture"]["provider_fixture_id"], "espn-1")

    async def test_post_tipoff_observation_rejected(self):
        with self.assertRaises(ValueError):
            await persist_resolved_nba_prematch(
                adapter=self.adapter, ledger=self.ledger, core=self.core,
                baseline_store=self.series_store,
                observed_at_utc=self.tipoff)

    async def test_future_dated_prediction_rejected(self):
        self.core.meta["generated_at"] = self.tipoff - 30
        with self.assertRaises(ValueError):
            await persist_resolved_nba_prematch(
                adapter=self.adapter, ledger=self.ledger, core=self.core,
                baseline_store=self.series_store,
                observed_at_utc=self.tipoff - 60)

    async def test_missing_source_metadata_rejected(self):
        self.core.meta.pop("home_sources")
        with self.assertRaisesRegex(ValueError, "home baseline"):
            await persist_resolved_nba_prematch(
                adapter=self.adapter, ledger=self.ledger, core=self.core,
                baseline_store=self.series_store,
                observed_at_utc=self.tipoff - 60)

    async def test_insufficient_baseline_sample_rejected(self):
        self.core.meta["away_baseline_games"] = 5
        with self.assertRaisesRegex(ValueError, "away baseline"):
            await persist_resolved_nba_prematch(
                adapter=self.adapter, ledger=self.ledger, core=self.core,
                baseline_store=self.series_store,
                observed_at_utc=self.tipoff - 60)

    async def test_manual_source_inside_verified_label_rejected(self):
        self.core.meta["home_sources"] = ["ESPN", "MANUAL_BASELINE"]
        with self.assertRaisesRegex(ValueError, "home baseline"):
            await persist_resolved_nba_prematch(
                adapter=self.adapter, ledger=self.ledger, core=self.core,
                baseline_store=self.series_store,
                observed_at_utc=self.tipoff - 60)
        with self.ledger._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM predictions").fetchone()[0], 0)

    async def test_empty_source_label_rejected_without_write(self):
        self.core.meta["away_sources"] = [""]
        with self.assertRaisesRegex(ValueError, "away baseline"):
            await persist_resolved_nba_prematch(
                adapter=self.adapter, ledger=self.ledger, core=self.core,
                baseline_store=self.series_store,
                observed_at_utc=self.tipoff - 60)
        with self.ledger._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM predictions").fetchone()[0], 0)

    async def test_manual_baseline_rejected(self):
        self.core.meta["data_quality"] = "MANUAL_BASELINE"
        with self.assertRaises(ValueError):
            await persist_resolved_nba_prematch(
                adapter=self.adapter, ledger=self.ledger, core=self.core,
                baseline_store=self.series_store,
                observed_at_utc=self.tipoff - 60)


if __name__ == "__main__":
    unittest.main()
