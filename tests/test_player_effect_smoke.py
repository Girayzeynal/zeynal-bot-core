"""Actual numerical before/after smoke; inputs are all manufactured."""
import math
from unittest import TestCase

from hybrid_engine.player_effect_smoke import execute, VERSION


class SyntheticPlayerBayesRuntimeTests(TestCase):
    def test_actual_rotation_and_bayesian_qmc_are_executed_and_not_live(self):
        result=execute()
        self.assertEqual(result['format'],VERSION)
        # A simulation that changes minutes but leaves the fitted player
        # forecast unchanged is a FAILED sensitivity test, never a pass.
        self.assertEqual(result['status'],'SYNTHETIC_PIPELINE_PASSED')
        self.assertTrue(result['score_sensitivity_observed'])
        self.assertGreater(max(abs(x) for x in result['PLAYER_BAYES_DELTA'].values()),1e-7)
        self.assertFalse(result['evidence_is_real_game'])
        self.assertFalse(result['player_effect_is_live'])
        self.assertFalse(result['production_enabled'])
        self.assertFalse(result['original_forecasts_changed'])
        self.assertEqual(result['network_requests_made'],0)
        self.assertEqual(result['QMC_scenarios'],10000)
        self.assertGreaterEqual(result['synthetic_fit_games'],30)
        self.assertAlmostEqual(result['home_rotation_minutes_before'],240)
        self.assertAlmostEqual(result['home_rotation_minutes_after'],240)
        self.assertGreater(result['missing_player_minutes_before'],0)
        self.assertEqual(result['missing_player_minutes_after'],0)
        self.assertGreater(sum(r['minute_change'] for r in
            result['replacement_minutes_top4']),0)
        score=result['PLAYER_BAYES_AFTER']
        self.assertTrue(all(math.isfinite(score[s]) for s in ('home','away')))
        for side in ('home','away'):
            self.assertAlmostEqual(result['PLAYER_BAYES_DELTA'][side],
                result['PLAYER_BAYES_AFTER'][side]-
                result['PLAYER_BAYES_BEFORE'][side],places=2)
