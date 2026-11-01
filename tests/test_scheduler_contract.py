import unittest
from unittest.mock import AsyncMock, MagicMock

from dynamic_scheduler import run_analysis
from faz13_engine import Faz13CoreOutput, FixtureContext, TeamAverages


class SchedulerContractTests(unittest.IsolatedAsyncioTestCase):
    def make_core(self):
        return Faz13CoreOutput(
            ctx=FixtureContext("NBA", "2026-11-01", "Boston Celtics", "New York Knicks"),
            home_avg=TeamAverages(112.0, 108.0, 99.0, 10.0),
            away_avg=TeamAverages(109.0, 111.0, 98.0, 10.0),
            total_band=(205, 235), home_band=(100, 120), away_band=(100, 120),
            ou_direction="NO_EDGE", quarters={}, blowout_risk="LOW", tempo_flag="NORMAL",
            meta={"confidence": 0.7, "confidence_pct": 70.0, "data_quality": "VERIFIED_BASELINE",
                  "expected_total": 220.0},
        )

    async def test_prematch_pipeline_does_not_call_live_faz16(self):
        core = self.make_core()
        faz13 = MagicMock()
        faz13.run_prematch = AsyncMock(return_value=core)
        faz17 = MagicMock()
        faz17.enrich_with_market = AsyncMock(return_value=core)
        faz22 = MagicMock()
        faz22.score_and_finalize.side_effect = lambda value: value
        faz23 = MagicMock()
        faz23.record_snapshot = AsyncMock()
        engines = {"faz13": faz13, "faz17": faz17, "faz22": faz22, "faz23": faz23,
                   "faz16": MagicMock()}

        result = await run_analysis(engines, "NBA", "2026-11-01", "Boston Celtics",
                                    "New York Knicks", True, fixture_id="12345")

        self.assertTrue(result)
        engines["faz16"].assert_not_called()
        self.assertEqual(core.meta["faz16_status"], "NOT_APPLICABLE_PREMATCH")
        self.assertEqual(core.meta["prematch_simulation_status"], "NOT_RUN")
        faz23.record_snapshot.assert_awaited_once_with(core)

    async def test_missing_provenance_fails_closed_and_is_not_snapshotted(self):
        core = self.make_core()
        core.meta.pop("data_quality")
        faz13 = MagicMock()
        faz13.run_prematch = AsyncMock(return_value=core)
        faz23 = MagicMock()
        faz23.record_snapshot = AsyncMock()
        engines = {"faz13": faz13, "faz17": MagicMock(), "faz22": MagicMock(), "faz23": faz23}

        result = await run_analysis(engines, "NBA", "2026-11-01", "Boston Celtics",
                                    "New York Knicks", False, fixture_id="12345")

        self.assertFalse(result)
        faz23.record_snapshot.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
