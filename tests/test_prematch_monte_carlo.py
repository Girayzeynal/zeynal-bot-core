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
        self.assertAlmostEqual(result.home_regulation_win_probability + result.away_regulation_win_probability + result.regulation_tie_probability, 1.0)

    def test_result_explicitly_declares_regulation_only_scope(self):
        result = self.engine.simulate(self.request())
        self.assertEqual(result.model_scope, 'REGULATION_ONLY')
        self.assertGreaterEqual(result.observed_score_correlation, -1.0)
        self.assertLessEqual(result.observed_score_correlation, 1.0)

    def test_overtime_period_count_is_rejected(self):
        with self.assertRaises(ValueError):
            self.engine.simulate(self.request(periods=5))

    def test_market_probabilities_partition_sample_space(self):
        result = self.engine.simulate(self.request())
        self.assertAlmostEqual(result.over_probability + result.under_probability + result.push_probability, 1.0)

    def test_invalid_non_finite_input_is_rejected(self):
        with self.assertRaises(ValueError):
            self.engine.simulate(self.request(home_mean=float('nan')))

    def test_score_correlation_matches_requested_parameter(self):
        result = self.engine.simulate(self.request(score_correlation=0.40, simulations=30000))
        self.assertIsNotNone(result.observed_score_correlation)
        self.assertAlmostEqual(result.observed_score_correlation, 0.40, delta=0.025)

    def test_score_standard_deviations_remain_calibrated(self):
        result = self.engine.simulate(self.request(score_correlation=0.40, simulations=30000))
        # Rounding introduces a small discretization effect.
        self.assertAlmostEqual(result.expected_home_score, 112.0, delta=0.25)
        self.assertAlmostEqual(result.expected_away_score, 108.0, delta=0.25)

    def test_non_integer_seed_is_rejected(self):
        with self.assertRaises(ValueError):
            self.engine.simulate(self.request(seed=7.5))

    def test_non_integer_simulation_count_is_rejected(self):
        with self.assertRaises(ValueError):
            self.engine.simulate(self.request(simulations=2000.5))

    def test_invalid_correlation_is_rejected(self):
        with self.assertRaises(ValueError):
            self.engine.simulate(self.request(score_correlation=1.0))


if __name__ == '__main__':
    unittest.main()
