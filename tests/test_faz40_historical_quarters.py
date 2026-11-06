import unittest

from faz40_historical_quarters import quarter_history_features


def make_rows(league="NBA", team="BOS"):
    return [
        dict(league=league, team=team, game_id=f"g{i}",
             ended_at_utc=i * 10, observed_at_utc=i * 10 + 1,
             score_scope="REGULATION_ONLY", quarters=[20+i, 21+i, 22+i, 23+i])
        for i in range(1, 7)
    ]


class HistoricalQuarterTests(unittest.TestCase):
    def features(self, rows=None, **kwargs):
        options = dict(cutoff_utc=100, league="NBA", team="BOS", min_games=5)
        options.update(kwargs)
        return quarter_history_features(make_rows() if rows is None else rows, **options)

    def test_last_five_and_additive_halves(self):
        features = self.features()
        self.assertEqual(features["sample_games"], 5)
        self.assertEqual(features["quarter_means"], [24, 25, 26, 27])
        self.assertEqual(features["first_half_mean"], 49)
        self.assertEqual(features["second_half_mean"], 53)
        self.assertEqual(features["regulation_total_mean"], 102)
        self.assertEqual(features["second_half_delta"], 4)

    def test_league_isolation(self):
        with self.assertRaisesRegex(ValueError, "contamination"):
            self.features(make_rows(league="EUROLEAGUE"))

    def test_team_isolation(self):
        with self.assertRaisesRegex(ValueError, "contamination"):
            self.features(make_rows(team="NYK"))

    def test_future_observation_rejected(self):
        rows = make_rows()
        rows[0]["observed_at_utc"] = 101
        with self.assertRaisesRegex(ValueError, "cutoff"):
            self.features(rows)

    def test_overtime_scope_rejected(self):
        rows = make_rows()
        rows[0]["score_scope"] = "FINAL_WITH_OT"
        with self.assertRaisesRegex(ValueError, "scope"):
            self.features(rows)

    def test_duplicate_game_rejected(self):
        rows = make_rows()
        rows[1]["game_id"] = rows[0]["game_id"]
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.features(rows)

    def test_missing_quarter_rejected(self):
        rows = make_rows()
        rows[0]["quarters"] = [20, 21, 22]
        with self.assertRaisesRegex(ValueError, "quarter"):
            self.features(rows)

    def test_insufficient_history_rejected(self):
        with self.assertRaisesRegex(ValueError, "Insufficient"):
            self.features(make_rows()[:4])

    def test_euroleague_supported_with_its_own_history(self):
        result = self.features(make_rows("EUROLEAGUE", "ABC"),
                               league="EUROLEAGUE", team="ABC")
        self.assertEqual(result["league"], "EUROLEAGUE")
        self.assertEqual(result["calibration_status"], "NOT_ESTABLISHED")


if __name__ == "__main__":
    unittest.main()
