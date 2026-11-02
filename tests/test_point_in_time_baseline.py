"""Regression tests for point-in-time NBA baseline selection."""
import tempfile
import unittest

from baseline.team_baseline_store import TeamBaselineStore


class PointInTimeBaselineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = TeamBaselineStore(self.temp.name)

    def add(self, timestamp, points=110):
        self.store.append_game(
            "NBA", "BOS", points, 100, 100.0, True,
            ts_utc=timestamp,
            timestamp_precision="exact",
        )

    def test_excludes_fixture_and_future_games(self):
        for timestamp in (100, 200, 300, 400, 500, 600, 700, 800):
            self.add(timestamp)
        before = self.store.get_series_before("NBA", "BOS", 600, 20)
        self.assertEqual([r.ts_utc for r in before], [100, 200, 300, 400, 500])

    def test_insufficient_history_fails_closed(self):
        for timestamp in (100, 200, 300, 400, 500):
            self.add(timestamp)
        self.assertIsNone(
            self.store.compute_baseline_before("NBA", "BOS", 600, min_games=6)
        )

    def test_historical_average_ignores_later_outlier(self):
        for timestamp in (100, 200, 300, 400, 500, 600):
            self.add(timestamp)
        self.add(700, 190)
        baseline = self.store.compute_baseline_before(
            "NBA", "BOS", 700, n_games=10, min_games=6
        )
        self.assertIsNotNone(baseline)
        self.assertEqual(baseline["n_games"], 6)
        self.assertAlmostEqual(baseline["pts_for"], 110.0)

    def test_repeated_fetch_does_not_inflate_sample(self):
        # Repeated fetches are identical records, not different scores
        # sharing an ambiguous timestamp.
        for _ in range(2):
            self.store.append_game(
                "NBA", "BOS", 105, 100, 100.0, True,
                ts_utc=100, game_id="game-100", source="test",
                timestamp_precision="exact",
            )
        records = self.store.get_series("NBA", "BOS", 10)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].pts_for, 105)

    def test_same_timestamp_without_identity_preserves_distinct_games(self):
        self.add(100, 105)
        self.add(100, 115)
        records = self.store.get_series("NBA", "BOS", 10)
        self.assertEqual(len(records), 2)
        self.assertEqual(sorted(r.pts_for for r in records), [105, 115])

    def test_same_provider_identity_conflicting_score_rejected(self):
        self.store.append_game(
            "NBA", "BOS", 105, 100, 100.0, True,
            ts_utc=100, game_id="game-100", source="test",
            timestamp_precision="exact",
        )
        with self.assertRaises(ValueError):
            self.store.append_game(
                "NBA", "BOS", 115, 100, 100.0, True,
                ts_utc=100, game_id="game-100", source="test",
                timestamp_precision="exact",
            )


if __name__ == "__main__":
    unittest.main()
