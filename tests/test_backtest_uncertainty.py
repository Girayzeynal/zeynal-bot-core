import unittest
from backtest_uncertainty import bootstrap_mean_interval


class BootstrapIntervalTests(unittest.TestCase):
    def test_no_interval_for_one_game(self):
        self.assertIsNone(bootstrap_mean_interval([3.0]))

    def test_reproducible_and_contains_point_estimate_for_constant_errors(self):
        a = bootstrap_mean_interval([2.0] * 20)
        b = bootstrap_mean_interval([2.0] * 20)
        self.assertEqual(a, b)
        self.assertEqual((a["lower"], a["estimate"], a["upper"]), (2.0, 2.0, 2.0))

    def test_nonfinite_rejected(self):
        with self.assertRaises(ValueError):
            bootstrap_mean_interval([1.0, float("nan")])

    def test_variable_errors_bounded(self):
        interval = bootstrap_mean_interval([0.0, 2.0, 4.0, 6.0] * 5)
        self.assertLessEqual(interval["lower"], interval["estimate"])
        self.assertLessEqual(interval["estimate"], interval["upper"])


if __name__ == "__main__":
    unittest.main()
