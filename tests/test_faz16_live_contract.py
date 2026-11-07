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


class Faz16StrictClockTests(unittest.TestCase):
    def run_live(self, snapshot=None, **kwargs):
        return faz16_live_recalibrate(220, 12, None,
                                     snapshot or LiveSnapshot(1, 120, 30), **kwargs)

    def test_fractional_boolean_and_string_clock_fields_rejected(self):
        for field in ("period", "sec_elapsed_in_period", "points_total_so_far"):
            for value in (True, 1.5, "1", float("nan"), None):
                snap = LiveSnapshot(1, 120, 30)
                setattr(snap, field, value)
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.run_live(snap)

    def test_invalid_guards_and_thresholds_rejected_before_early_return(self):
        for options in ({"early_guard_sec": -1}, {"early_guard_sec": 721},
                        {"early_guard_sec": 1.5}, {"early_guard_sec": True},
                        {"drift_soft_pct": -1}, {"drift_trigger_pct": 3},
                        {"drift_soft_pct": float("nan")},
                        {"drift_trigger_pct": float("inf")},
                        {"drift_trigger_pct": True}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.run_live(LiveSnapshot(1, 30, 8), **options)

    def test_clock_uses_canonical_registered_league(self):
        self.assertEqual(self.run_live(league=" euro league "),
                         self.run_live(league="EUROLEAGUE"))
        with self.assertRaises(ValueError):
            self.run_live(LiveSnapshot(1, 601, 30), league="EUROLEAGUE")
        self.run_live(LiveSnapshot(1, 601, 30), league="NBA")

    def test_completed_clock_and_overtime_not_projected(self):
        for league, seconds in (("NBA", 720), ("EUROLEAGUE", 600)):
            for snap in (LiveSnapshot(4, seconds, 180), LiveSnapshot(5, 1, 180)):
                with self.subTest(league=league, snap=snap), self.assertRaises(ValueError):
                    self.run_live(snap, league=league)

    def test_zero_clock_cannot_contain_points(self):
        with self.assertRaises(ValueError):
            self.run_live(LiveSnapshot(1, 0, 1))
        self.assertEqual(self.run_live(LiveSnapshot(1, 0, 0)).live_mean_total, 220)

    def test_scope_and_calibration_are_explicit(self):
        result = self.run_live()
        self.assertEqual(result.model_scope, "REGULATION_ONLY")
        self.assertEqual(result.calibration_status, "NOT_ESTABLISHED")
        self.assertEqual(result.confidence_boost, 0)
        self.assertEqual(result, self.run_live())


if __name__ == "__main__":
    unittest.main()
