import asyncio
import unittest
from dataclasses import dataclass

from faz13_engine import Faz13Engine, PrematchRequest
from league_profiles import get_league_profile


@dataclass
class FakeBaseline:
    league: str = "NBA"
    team: str = "BOS"
    n_games: int = 10
    pts_for: float = 112.0
    pts_against: float = 108.0
    pace: float = 99.0
    updated_ts: int = 1_800_000_000


class FakeStore:
    def __init__(self, records=None):
        self.records = records or {}

    def get(self, league, team):
        return self.records.get((league, team))


class Faz13BaselineContractTests(unittest.TestCase):
    def make_engine(self, store):
        engine = Faz13Engine("test-key", "https://example.invalid", baseline_store=store)
        # Tests must not perform network access.
        engine.espn = None
        return engine

    def test_reads_canonical_team_baseline_store(self):
        store = FakeStore({
            ("NBA", "BOS"): FakeBaseline(team="BOS"),
            ("NBA", "NYK"): FakeBaseline(team="NYK", pts_for=109.0),
        })
        engine = self.make_engine(store)

        result = asyncio.run(engine.run_prematch(
            PrematchRequest(1, "NBA", "2026-11-01", "BOS", "NYK")
        ))

        self.assertEqual(result.meta["data_quality"], "VERIFIED_BASELINE")
        self.assertEqual(result.meta["home_baseline_games"], 10)
        self.assertEqual(result.meta["away_baseline_games"], 10)
        self.assertGreater(result.meta["confidence_pct"], 0)

    def test_missing_baseline_fails_closed_without_fabricated_average(self):
        engine = self.make_engine(FakeStore())

        with self.assertRaisesRegex(ValueError, "Güvenilir baseline bulunamadı"):
            asyncio.run(engine.run_prematch(
                PrematchRequest(2, "NBA", "2026-11-01", "BOS", "NYK")
            ))

    def test_unregistered_league_does_not_inherit_euroleague_profile(self):
        with self.assertRaisesRegex(ValueError, "No calibrated profile"):
            get_league_profile("EuroCup")


if __name__ == "__main__":
    unittest.main()
