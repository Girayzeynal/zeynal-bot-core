import unittest

from faz16_engine.faz16_simulation import LiveSnapshot, faz16_live_recalibrate


class Faz16LiveContractTests(unittest.TestCase):
    def test_early_snapshot_preserves_prematch_distribution(self):
        result = faz16_live_recalibrate(
            220.0, 12.0, None, LiveSnapshot(1, 30, 8), league="NBA"
        )
        self.assertEqual(result.live_mean_total, 220.0)
        self.assertEqual(result.live_std_total, 12.0)
        self.assertEqual(result.live_edge_flag, "STILL_NO_EDGE")

    def test_rejects_period_outside_league_clock(self):
        with self.assertRaisesRegex(ValueError, "snapshot.period"):
            faz16_live_recalibrate(
                220.0, 12.0, None, LiveSnapshot(5, 0, 100), league="NBA"
            )

    def test_rejects_non_finite_prematch_mean(self):
        with self.assertRaisesRegex(ValueError, "finite and positive"):
            faz16_live_recalibrate(
                float("nan"), 12.0, None, LiveSnapshot(1, 120, 30), league="NBA"
            )

    def test_rejects_unregistered_league(self):
        with self.assertRaisesRegex(ValueError, "No calibrated profile"):
            faz16_live_recalibrate(
                220.0, 12.0, None, LiveSnapshot(1, 120, 30), league="EuroCup"
            )


if __name__ == "__main__":
    unittest.main()
