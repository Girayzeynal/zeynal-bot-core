import unittest
from backtest_uncertainty import moving_block_mean_interval, block_length_sensitivity


class BlockBootstrapTests(unittest.TestCase):
    def test_insufficient_observations(self):
        self.assertIsNone(moving_block_mean_interval([1.0] * 9))

    def test_constant_sample_and_reproducibility(self):
        a = moving_block_mean_interval([3.0] * 20)
        self.assertEqual(a, moving_block_mean_interval([3.0] * 20))
        self.assertEqual((a["lower"], a["estimate"], a["upper"]), (3.0, 3.0, 3.0))
        self.assertEqual(a["method"], "circular_moving_block_bootstrap")

    def test_sensitivity_tracks_eligible_lengths(self):
        result = block_length_sensitivity([1.0] * 12)
        self.assertEqual(result["eligible_block_lengths"], 2)
        self.assertIsNotNone(result["block_sizes"]["3"])
        self.assertIsNotNone(result["block_sizes"]["5"])
        self.assertIsNone(result["block_sizes"]["7"])
        self.assertIsNone(result["block_sizes"]["10"])
        self.assertEqual(result["interval_width_min"], 0.0)
        self.assertEqual(result["selection_policy"],
                         "descriptive_only_no_automatic_best_block")

    def test_duplicate_block_lengths_rejected(self):
        with self.assertRaises(ValueError):
            block_length_sensitivity([1.0] * 20, (3, 3))

    def test_invalid_block_rejected(self):
        with self.assertRaises(ValueError):
            moving_block_mean_interval([1.0] * 20, block_size=1)

    def test_nonfinite_rejected(self):
        with self.assertRaises(ValueError):
            moving_block_mean_interval([1.0] * 10 + [float("inf")])


if __name__ == "__main__":
    unittest.main()
