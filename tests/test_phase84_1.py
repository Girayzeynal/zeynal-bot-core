"""Research regressions: no production scores, lines, or confidence policy changed."""
from copy import deepcopy
from unittest import TestCase
import numpy as np

from hybrid_engine.data import feature_cut
from hybrid_engine.diagnostics import signed_bias, calibration_readiness
from hybrid_engine.distributions import gaussian_forecast
from hybrid_engine.evaluation import v1_forecast
from hybrid_engine.markets import market_grid
from hybrid_engine.observed_markets import implied_prices, observe_espn, evaluate_observation
from hybrid_engine.statistics import paired_cluster_interval, paired_market_interval, paired_winner_interval
from hybrid_engine.walkforward import serialize, LINE_MARKETS, line_offsets
from tests.test_hybrid_models import synthetic_cohort
from tests.test_observed_markets import receipt, NOW


class Phase841Tests(TestCase):
    def rows(self):
        c=synthetic_cohort(50);cut=feature_cut(c,c[40][0]);f=v1_forecast(cut)
        return cut,f,serialize(cut,f,c[40][0],0.,0,'synthetic',dict(observed_at_utc=cut.cutoff_utc-10,ingested_at_utc=cut.cutoff_utc-9))

    def test_all_quarters_and_halves_have_three_scenario_lines(self):
        cut,f,r=self.rows()
        self.assertEqual(len(r['line_grid']),30)
        self.assertEqual({m['market'] for m in r['line_grid']},set(LINE_MARKETS))
        for m in r['line_grid']:
            self.assertAlmostEqual(sum(m['probabilities'].values()),1)
            self.assertIsNone(m['confidence_index'])
            self.assertIn(m['offset'],line_offsets(m['market']))
        for kind in ('2Q','3Q','4Q','2H'):
            entry=next(m for m in r['line_grid'] if m['market']==kind and m['offset']==0)
            self.assertEqual(entry['probabilities'],r['markets'][kind]['probabilities'])

    def test_grid_extension_does_not_change_v1_prediction_or_existing_lines(self):
        cut,f,r=self.rows()
        self.assertEqual(r['prediction'],f.summary())
        for kind in ('1Q','1H','TOTAL','HOME','AWAY','HOME_HANDICAP'):
            center=next(m['line'] for m in r['line_grid'] if m['market']==kind and m['offset']==0)
            self.assertEqual(sorted(m['line'] for m in r['line_grid'] if m['market']==kind),
                [center+o for o in line_offsets(kind)])
            for m in [m for m in r['line_grid'] if m['market']==kind]:
                self.assertEqual(m['probabilities'],f.market('MARGIN' if kind=='HOME_HANDICAP' else kind,-m['line'] if kind=='HOME_HANDICAP' else m['line']))

    def test_new_periods_fail_closed_without_verified_calibration(self):
        f=gaussian_forecast([110,100],[10,10],np.ones((4,2)),method='ANALYTIC')
        for m in market_grid(f,{k:[50.5] for k in ('2Q','3Q','4Q','2H')},model_digest='test',prediction_utc=NOW):
            self.assertEqual(m['status'],'ABSTAIN');self.assertIsNone(m['confidence_index'])

    def test_bias_diagnostics_preserve_signed_errors_and_abstain_small_clusters(self):
        _,_,r=self.rows();r['prediction']['quarters']=(np.array(r['actual_quarters'])+1).tolist()
        b=signed_bias([r]);self.assertEqual(b['markets']['TOTAL']['mean_signed_error'],8)
        self.assertEqual(b['markets']['1Q']['mean_signed_error'],2)
        self.assertIsNone(b['markets']['TOTAL']['familywise_interval']);self.assertFalse(b['score_correction_applied'])
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):signed_bias([r,r])

    def test_period_and_team_error_intervals_have_expanded_multiple_testing_family(self):
        _,_,r=self.rows();v=paired_cluster_interval([r],[deepcopy(r)])
        self.assertEqual(v['family_size'],13)
        for kind in ('second_quarter_mae','third_quarter_mae','fourth_quarter_mae','second_half_mae','home_mae','away_mae'):
            self.assertIn(kind,v['metrics']);self.assertIsNone(v['metrics'][kind]['interval'])
        m=paired_market_interval([r],[deepcopy(r)],'2Q',0.)
        self.assertEqual(m['family_size'],30)

    def test_raw_oos_curves_do_not_authorize_confidence_or_posthoc_fit(self):
        _,_,r=self.rows();x=calibration_readiness([r])
        self.assertEqual(x['verified_profiles'],0);self.assertIsNone(x['confidence_index'])
        self.assertFalse(x['test_labels_used_for_calibration'])
        self.assertEqual(x['maximum_exact_model_market_line_oos_games'],1)

    def test_no_vig_prices_are_normalized_and_not_true_probability_claims(self):
        p=implied_prices(2,2);self.assertEqual(p['over_or_home'],.5);self.assertEqual(p['overround'],0)
        p=implied_prices(1.8,2.1)
        self.assertAlmostEqual(p['over_or_home']+p['under_or_away'],1)
        self.assertGreater(p['overround'],0)
        for a,b in [(1,2),(0,2),(True,2),(float('nan'),2)]:
            with self.assertRaises(ValueError):implied_prices(a,b)

    def test_observed_prices_do_not_authorize_unverified_market_edge(self):
        q=observe_espn(receipt(),now_utc=NOW)['quotes'][0]
        f=gaussian_forecast([110,100],[10,10],np.ones((4,2)),method='ANALYTIC')
        r=evaluate_observation(q,f,trusted_sha256=q['sha256'],model_digest='test',prediction_utc=NOW)
        self.assertEqual(r['observed_price_probabilities']['over_or_home'],.5)
        self.assertIsNone(r['comparable_model_market_edge']);self.assertIsNone(r['recommended_direction'])
        self.assertEqual(r['status'],'ABSTAIN')

    def test_failed_delivery_probe_does_not_satisfy_normal_readiness_gate(self):
        from hybrid_engine.acceptance import verified_runtime
        from tests.test_preparation_acceptance import CombinedAcceptanceTests
        r=CombinedAcceptanceTests().report();r['injected_delivery_errors']=[429,503]
        self.assertFalse(verified_runtime(r,{'code':'synthetic'}))
        r=CombinedAcceptanceTests().report();r['successful_message_deliveries']=23
        self.assertFalse(verified_runtime(r,{'code':'synthetic'}))

    def test_winner_intervals_require_same_games_and_explicit_small_sample_abstention(self):
        _,_,r=self.rows();s=deepcopy(r)
        out=paired_winner_interval([r],[s])
        self.assertEqual(out['n'],1);self.assertIsNone(out['metrics']['brier']['familywise_interval'])
        s['start_utc']+=1
        with self.assertRaisesRegex(ValueError,'IDENTICAL'):paired_winner_interval([r],[s])
