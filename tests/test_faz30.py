"""Synthetic metrics/paired/variance tests plus real trimmed period replay."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from model_evaluation import score_metrics,paired_compare,walk_forward_plan
from period_feature_layer import materialize_period,select_available,export_observations
from simulation_assumptions import variance_contract,sensitivity
from prematch_monte_carlo import PrematchSimulationInput
from prediction_inputs import digest


def row(fixture='a',version='v1',predicted=10,start=20,observed=30,home=110,away=95):
    return dict(fixture_id=fixture,model='TEST_MODEL',model_version=version,scope='FINAL_WITH_OT',
                generated_at=predicted,start_utc=start,result_observed_utc=observed,
                expected_home=home,expected_away=away,actual_home=100,actual_away=90)


class MetricTests(unittest.TestCase):
    def test_team_total_margin_metrics_distinct(self):
        result=score_metrics([row()])
        self.assertEqual(result['home_mae'],10);self.assertEqual(result['away_mae'],5)
        self.assertEqual(result['total_mae'],15);self.assertEqual(result['margin_mae'],5)
        self.assertEqual(result['home_rmse'],10)

    def test_paired_uses_only_common_games_with_identical_cutoff(self):
        left=[row(),row('only-left')];right=[row(version='v2',home=100,away=90)]
        result=paired_compare(left,right)
        self.assertEqual(result['paired_games'],1)
        self.assertEqual(result['unmatched_left'],1)
        self.assertEqual(result['metrics']['right_minus_left']['home_mae'],-10)

    def test_no_common_or_incompatible_scope_is_not_comparable(self):
        self.assertEqual(paired_compare([row()],[row('other','v2')])['status'],'NO_COMMON_GAMES')
        other={**row(version='v2'),'scope':'REGULATION_ONLY'}
        self.assertEqual(paired_compare([row()],[other])['status'],'INCOMPATIBLE_SCOPE')
        other={**row(version='v2'),'generated_at':11}
        self.assertEqual(paired_compare([row()],[other])['status'],'PREDICTION_CUTOFF_MISMATCH')

    def test_mixed_versions_duplicate_or_changed_actuals_rejected(self):
        for rows in ([row(),row()], [row(),row('b','v2')]):
            with self.assertRaises(ValueError):score_metrics(rows)
        with self.assertRaises(ValueError):paired_compare([row()],[{**row(version='v2'),'actual_home':101}])

    def test_walk_forward_excludes_future_equal_time_and_other_versions(self):
        rows=[row('a',predicted=10,start=20,observed=100),row('b',predicted=40,start=50,observed=80),
              row('c',predicted=100,start=110,observed=120),row('other-version','v2',predicted=5,start=6,observed=7)]
        plan=walk_forward_plan(rows,1)
        fold=next(f for f in plan['folds'] if f['fixture_id']=='c')
        self.assertEqual(fold['training_ids'],['b'])
        self.assertFalse(plan['parameters_fitted']);self.assertFalse(plan['original_forecasts_changed'])


class PeriodLayerTests(unittest.TestCase):
    def source(self):
        return json.loads((Path(__file__).parent/'fixtures/faz29-real-final-periods.json').read_text())['401909925']

    def materialize(self):
        now=int(time.time())
        return materialize_period(self.source(),source_observed_utc=now-60,
                                  source_evidence_sha256='a'*64,input_ref={'synthetic_test_ref':True})

    def test_source_time_does_not_backdate_materialized_features(self):
        record=self.materialize();p=record['payload']
        self.assertEqual(select_available([record],p['source_observed_utc']+1),[])
        self.assertEqual(select_available([record],p['materialized_utc']),[])
        self.assertEqual(len(select_available([record],p['materialized_utc']+1)),1)
        self.assertEqual(len(export_observations([record,deepcopy(record)])),1)

    def test_regulation_and_ot_are_separate_replayable_targets(self):
        raw=self.source();comp=raw['header']['competitions'][0]
        for side,lines,score in ((0,[25,25,25,25,10],110),(1,[25,25,25,25,8],108)):
            comp['competitors'][side]['linescores']=[{'displayValue':str(v)} for v in lines]
            comp['competitors'][side]['score']=str(score)
        comp['status']['period']=5
        record=materialize_period(raw,source_observed_utc=int(time.time()),source_evidence_sha256='a'*64,input_ref={})
        self.assertEqual(record['payload']['regulation']['home'],100)
        self.assertEqual(record['payload']['final']['home'],110)
        self.assertEqual(record['payload']['overtime_home'],[10])
        self.assertEqual(len(export_observations([record])),1)

    def test_rehashed_semantic_tamper_rejected(self):
        record=self.materialize();record['payload']['regulation']['home']+=1
        record['sha256']=digest(record['payload'])
        with self.assertRaises(ValueError):export_observations([record])

    def test_future_source_time_rejected(self):
        with self.assertRaises(ValueError):
            materialize_period(self.source(),source_observed_utc=int(time.time())+60,source_evidence_sha256='a'*64,input_ref={})

    def test_unknown_schema_or_source_rejected_even_if_rehashed(self):
        for field,value in (('schema_version',2),('provider','OTHER')):
            r=self.materialize();r['payload'][field]=value;r['sha256']=digest(r['payload'])
            with self.subTest(field=field),self.assertRaises(ValueError):export_observations([r])


class CoverageTests(unittest.TestCase):
    def test_raw_legacy_scores_are_not_adjusted_strength_or_verified_pace(self):
        from types import SimpleNamespace
        from prediction_inputs import seal_prediction_inputs
        from faz30 import input_coverage
        now=int(time.time())
        core=SimpleNamespace(ctx=SimpleNamespace(league='NBA',date='2026-11-05',home='A',away='B'),
                             meta={'generated_at':now,'expected_home':100,'expected_away':100})
        teams={side:dict(key=name,captured_at_utc=now-1,records=[dict(ts_utc=now-86400-i,
            pts_for=100,pts_against=100,pace=99,home=True,game_id=side+str(i),
            source='SYNTHETIC_TEST_PROVIDER',timestamp_precision='exact',pace_evidence=None) for i in range(6)])
            for side,name in (('home','A'),('away','B'))}
        snapshot=seal_prediction_inputs(core,teams['home'],teams['away'])
        coverage,features=input_coverage(snapshot)
        self.assertEqual(features,[])
        for team in coverage['teams'].values():
            self.assertEqual(team['raw_offense_games'],6)
            self.assertEqual(team['opponent_adjusted_strength'],'NOT_COMPUTED')
            self.assertEqual(team['pace_estimate_games'],0)
            self.assertEqual(team['source_time_verified_games'],0)
            self.assertEqual(team['fitted_home_advantage'],'NOT_ESTABLISHED')


class VarianceTests(unittest.TestCase):
    def test_correlation_changes_total_and_margin_variance_in_opposite_directions(self):
        low=variance_contract(10,8,-.35);high=variance_contract(10,8,.35)
        self.assertGreater(high['latent_total_std'],low['latent_total_std'])
        self.assertLess(high['latent_margin_std'],low['latent_margin_std'])
        with self.assertRaises(ValueError):variance_contract(10,9,-.9,8)
        with self.assertRaises(ValueError):variance_contract(True,9,0)

    def test_10000_draw_synthetic_covariance_sensitivity(self):
        base=PrematchSimulationInput(110,105,10,8,simulations=10000,seed=20261104)
        configs=[replace(base,score_correlation=c) for c in (-.35,0,.35)]
        results=sensitivity(configs)
        for result in results:
            self.assertAlmostEqual(result['observed_correlation'],result['assumptions']['correlation'],delta=.04)
            self.assertAlmostEqual(result['observed_total_std'],result['assumptions']['latent_total_std'],delta=.5)
        self.assertEqual(results,sensitivity(configs))
        with self.assertRaises(ValueError):sensitivity([replace(base,simulations=1000)])
