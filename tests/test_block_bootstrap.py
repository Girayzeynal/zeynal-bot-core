import unittest
from backtest_uncertainty import moving_block_mean_interval


class BlockBootstrapTests(unittest.TestCase):
    def test_insufficient_observations(self):
        self.assertIsNone(moving_block_mean_interval([1.0] * 9))

    def test_constant_sample_and_reproducibility(self):
        a = moving_block_mean_interval([3.0] * 20)
        self.assertEqual(a, moving_block_mean_interval([3.0] * 20))
        self.assertEqual((a["lower"], a["estimate"], a["upper"]), (3.0, 3.0, 3.0))
        self.assertEqual(a["method"], "circular_moving_block_bootstrap")

    def test_invalid_block_rejected(self):
        with self.assertRaises(ValueError):
            moving_block_mean_interval([1.0] * 20, block_size=1)

    def test_nonfinite_rejected(self):
        with self.assertRaises(ValueError):
            moving_block_mean_interval([1.0] * 10 + [float("inf")])


if __name__ == "__main__":
    unittest.main()
