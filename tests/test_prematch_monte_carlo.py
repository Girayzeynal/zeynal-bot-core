import unittest

from prematch_monte_carlo import PrematchMonteCarloEngine, PrematchSimulationInput


class PrematchMonteCarloTests(unittest.TestCase):
    def setUp(self):
        self.engine = PrematchMonteCarloEngine()

    def request(self, **kwargs):
        values = dict(home_mean=112, away_mean=108, home_std=10, away_std=9, simulations=2000, seed=77, market_total=220)
        values.update(kwargs)
        return PrematchSimulationInput(**values)

    def test_seed_reproduces_identical_result(self):
        first = self.engine.simulate(self.request())
        second = self.engine.simulate(self.request())
        self.assertEqual(first, second)

    def test_period_means_reconcile_to_team_means(self):
        result = self.engine.simulate(self.request())
        self.assertAlmostEqual(sum(result.period_home_means), result.expected_home_score, places=2)
        self.assertAlmostEqual(sum(result.period_away_means), result.expected_away_score, places=2)

    def test_probabilities_sum_to_one_including_ties(self):
        result = self.engine.simulate(self.request())
        self.assertAlmostEqual(result.home_win_probability + result.away_win_probability + result.tie_probability, 1.0)

    def test_market_probabilities_partition_sample_space(self):
        result = self.engine.simulate(self.request())
        self.assertAlmostEqual(result.over_probability + result.under_probability + result.push_probability, 1.0)

    def test_invalid_non_finite_input_is_rejected(self):
        with self.assertRaises(ValueError):
            self.engine.simulate(self.request(home_mean=float('nan')))

    def test_invalid_correlation_is_rejected(self):
        with self.assertRaises(ValueError):
            self.engine.simulate(self.request(score_correlation=1.0))


if __name__ == '__main__':
    unittest.main()
