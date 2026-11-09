"""Synthetic Monte Carlo sampling diagnostics; not predictive calibration."""
import math
import unittest
from prematch_monte_carlo import (PrematchMonteCarloEngine, PrematchSimulationInput,
                                 _binomial_diagnostic)


class SamplingDiagnosticsTests(unittest.TestCase):
    def test_wilson_matches_known_half_success_case(self):
        result = _binomial_diagnostic(500, 1000)
        self.assertAlmostEqual(result["standard_error"], math.sqrt(.25 / 1000))
        self.assertAlmostEqual(result["wilson95_lo"], .4690696, places=6)
        self.assertAlmostEqual(result["wilson95_hi"], .5309304, places=6)

    def test_zero_and_all_success_still_have_sampling_uncertainty(self):
        zero = _binomial_diagnostic(0, 1000)
        full = _binomial_diagnostic(1000, 1000)
        self.assertGreater(zero["wilson95_hi"], 0)
        self.assertLess(full["wilson95_lo"], 1)
        self.assertAlmostEqual(zero["wilson95_hi"], 1-full["wilson95_lo"])

    def test_increasing_sample_size_narrows_interval(self):
        small = _binomial_diagnostic(500, 1000)
        large = _binomial_diagnostic(5000, 10000)
        self.assertLess(large["wilson95_hi"]-large["wilson95_lo"],
                        small["wilson95_hi"]-small["wilson95_lo"])

    def request(self, **options):
        data = dict(home_mean=110, away_mean=100, home_std=10, away_std=9,
                    simulations=1000, seed=17)
        data.update(options)
        return PrematchSimulationInput(**data)

    def test_counts_and_probabilities_reconcile_with_public_output(self):
        result = PrematchMonteCarloEngine().simulate(self.request(market_total=210))
        diagnostics = result.sampling_diagnostics
        self.assertEqual(result.calibration_status, "NOT_ESTABLISHED")
        self.assertEqual(diagnostics["interpretation"], "monte_carlo_sampling_error_only")
        outcomes = diagnostics["outcomes"]
        for name, prob in (("home_regulation_win", result.home_regulation_win_probability),
                           ("away_regulation_win", result.away_regulation_win_probability),
                           ("regulation_tie", result.regulation_tie_probability),
                           ("over", result.over_probability), ("under", result.under_probability),
                           ("push", result.push_probability)):
            item = outcomes[name]
            self.assertEqual(item["count"]/item["trials"], prob)
            self.assertLessEqual(item["wilson95_lo"], prob + 1e-15)
            self.assertGreaterEqual(item["wilson95_hi"], prob - 1e-15)
        self.assertEqual(sum(outcomes[k]["count"] for k in ("over", "under", "push")), 1000)
        self.assertAlmostEqual(diagnostics["expected_total_standard_error"],
                               result.total_std / math.sqrt(999))

    def test_market_absence_has_no_invented_market_diagnostics(self):
        result = PrematchMonteCarloEngine().simulate(self.request())
        self.assertEqual(set(result.sampling_diagnostics["outcomes"]),
                         {"home_regulation_win", "away_regulation_win", "regulation_tie"})
        self.assertIsNone(result.over_probability)

    def test_boolean_numeric_parameters_are_rejected(self):
        for name in ("home_mean", "away_mean", "home_std", "away_std", "shared_pace_std",
                     "score_correlation", "market_total"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                PrematchMonteCarloEngine().simulate(self.request(**{name: True}))
