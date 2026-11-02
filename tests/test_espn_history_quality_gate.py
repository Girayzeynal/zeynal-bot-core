import unittest
from datetime import datetime, timezone

from providers.espn_history_quality_gate import validate_history_for_fixture


def row(index, ts=1793000000):
    return {
        "provider_fixture_id": str(index),
        "start_ts_utc": ts + index,
        "home_team_id": "24",
        "away_team_id": "26",
        "actual_home": 110,
        "actual_away": 100,
    }


class HistoryQualityGateTests(unittest.TestCase):
    def setUp(self):
        self.cutoff = datetime(2026, 11, 2, tzinfo=timezone.utc)
        self.games = [row(i) for i in range(6)]

    def check(self, games, **kwargs):
        return validate_history_for_fixture(
            games, team_id="24", fixture_start_utc=self.cutoff,
            minimum=6, **kwargs)

    def test_scores_are_verified_without_pace(self):
        self.assertEqual(self.check(self.games, require_pace=False)["status"],
                         "score_history_verified")

    def test_pace_is_never_invented(self):
        self.assertEqual(self.check(self.games)["status"], "pace_unavailable")

    def test_future_fixture_leakage_is_rejected(self):
        future = [*self.games[:5], row(5, int(self.cutoff.timestamp()))]
        self.assertEqual(self.check(future, require_pace=False)["status"],
                         "invalid_record_or_leakage")

    def test_duplicate_fixture_id_is_rejected(self):
        self.assertEqual(self.check([*self.games[:5], self.games[0]],
                                    require_pace=False)["status"],
                         "invalid_record_or_leakage")

    def test_insufficient_history_is_rejected(self):
        self.assertEqual(self.check(self.games[:5], require_pace=False)["status"],
                         "insufficient_games")

    def test_wrong_team_is_rejected(self):
        bad = [dict(self.games[0], home_team_id="10", away_team_id="11"),
               *self.games[1:]]
        self.assertEqual(self.check(bad, require_pace=False)["status"],
                         "invalid_record_or_leakage")

    def test_naive_cutoff_is_rejected(self):
        self.assertEqual(validate_history_for_fixture(
            self.games, team_id="24",
            fixture_start_utc=datetime(2026, 11, 2))["status"], "invalid_input")


if __name__ == "__main__":
    unittest.main()
