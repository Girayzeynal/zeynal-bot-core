"""Synthetic native-row shape; real OT research fit/sampler and decision paths."""
from copy import deepcopy
import time
from unittest import TestCase
from unittest.mock import patch

import numpy as np
from hybrid_engine.data import Abstain
from hybrid_engine.distributions import Forecast
from hybrid_engine.decision_layer import DecisionDistribution
from hybrid_engine.overtime_research import fit,simulate,walk_forward


def cohort(now,league='NBA'):
    rows=[]
    for i in range(12):
        start=now-(20-i)*86400
        h=[25]*4;a=[24,26,25,25]
        if i%2:h += [8,7];a += [8,9]
        else:h += [10];a += [8]
        rows.append([dict(league=league,season='2026/2027',fixture_id='synthetic-ot-'+str(i),
            home_team_id='home',away_team_id='away',fixture_start_utc=start,
            observed_at_utc=start+7200,ingested_at_utc=start+7201,
            source_catalog_sha256='a'*64,periods=dict(home=h,away=a),final_scores=[sum(h),sum(a)])])
    return rows


class OvertimeResearchTests(TestCase):
    def setUp(self):
        self.now=int(time.time());timer=patch('time.time',side_effect=lambda:self.now)
        timer.start();self.addCleanup(timer.stop);self.rows=cohort(self.now)
        self.target=dict(league='NBA',season='2026/2027',fixture_id='future',fixture_start_utc=self.now+7200)
        self.paths=np.full((10000,4,2),25,dtype=np.int32);self.paths[::3,0,0]+=2

    def test_complete_ot_blocks_preserve_joint_regulation_and_multi_ot_dependence(self):
        model=fit(self.rows,cutoff_utc=self.now);before=self.paths.copy()
        for method in ('MC','RQMC_HALTON'):
            out=simulate(model,self.paths,self.target,asof_utc=self.now,method=method)
            ot=out['overtime_paths'];steps=out['overtime_steps'];reg=self.paths.sum(axis=1)
            self.assertTrue(np.array_equal(self.paths,before));self.assertTrue(np.array_equal(steps.sum(axis=1),ot))
            self.assertTrue(np.all(ot[reg[:,0]!=reg[:,1]]==0));self.assertTrue(np.all((reg+ot)[:,0]!=(reg+ot)[:,1]))
            # Multi-OT blocks have a tied first OT; never a second OT after an early winner.
            multiple=np.flatnonzero(np.any(steps[:,1]!=0,axis=1))
            self.assertGreater(len(multiple),0);self.assertTrue(np.all(steps[multiple,0,0]==steps[multiple,0,1]))
            forecast=Forecast('SYNTHETIC_REGULATION',self.paths.mean(axis=0),samples=self.paths)
            dist=DecisionDistribution(forecast,dict(inputs_available_max_utc=self.now-1,prediction_utc=self.now,
                tipoff_utc=self.target['fixture_start_utc']),overtime_paths=ot)
            self.assertTrue(np.array_equal(dist.values('FULL','TOTAL'),reg.sum(axis=1)))
            full=dist.values('FULL','TOTAL',include_overtime=True)
            self.assertTrue(np.array_equal(full,reg.sum(axis=1)+ot.sum(axis=1)))
            self.assertTrue(np.array_equal(full,dist.values('1H','TOTAL')+dist.values('2H','TOTAL',include_overtime=True)))
            self.assertFalse(out['metadata']['live_market_admission'])

    def test_each_league_is_fitted_independently_and_nba_coefficients_cannot_transfer(self):
        for league,duration in (('NBA',48),('EUROLEAGUE',40),('EUROCUP',40)):
            model=fit(cohort(self.now,league),cutoff_utc=self.now)
            self.assertEqual(model['payload']['regulation_minutes'],duration)
            target=dict(self.target,league=league)
            simulate(model,self.paths,target,asof_utc=self.now)
            with self.assertRaisesRegex(ValueError,'LEAGUE_SEASON'):
                simulate(model,self.paths,dict(target,league='OTHER'),asof_utc=self.now)

    def test_future_labels_never_change_past_fit_and_target_overlap_is_refused(self):
        model=fit(self.rows,cutoff_utc=self.now);changed=deepcopy(self.rows)
        future=deepcopy(changed[0][0]);future.update(fixture_id='future',fixture_start_utc=self.now+3600,
            observed_at_utc=self.now+7200,ingested_at_utc=self.now+7201)
        future['periods']['home']=[999]*5;changed.append([future])
        self.assertEqual(model,fit(changed,cutoff_utc=self.now))
        with self.assertRaisesRegex(ValueError,'TRAINING_OVERLAP'):
            simulate(model,self.paths,dict(self.target,fixture_id='synthetic-ot-0'),asof_utc=self.now)

    def test_sparse_or_invalid_ot_history_abstains_instead_of_inventing_overtime(self):
        with self.assertRaisesRegex(Abstain,'SIX_NATIVE_OT'):fit(self.rows[:5],cutoff_utc=self.now)
        broken=deepcopy(self.rows);broken[1][0]['periods']['home'][4]+=1;broken[1][0]['final_scores'][0]+=1
        with self.assertRaisesRegex(ValueError,'CANNOT_CONTINUE'):fit(broken,cutoff_utc=self.now)

    def test_five_minute_and_parameter_age_guards_remain_independent_of_sampling(self):
        model=fit(self.rows,cutoff_utc=self.now)
        self.now=self.target['fixture_start_utc']-301
        simulate(model,self.paths,self.target,asof_utc=self.now)
        for delta in (300,299,-1):
            self.now=self.target['fixture_start_utc']-delta
            with self.assertRaises(Abstain):simulate(model,self.paths,self.target,asof_utc=self.now)
        self.now+=86401
        with self.assertRaises(Abstain):simulate(model,self.paths,dict(self.target,fixture_start_utc=self.now+7200),asof_utc=self.now)

    def test_walk_forward_measures_disjoint_errors_without_waiting_for_hundred_games(self):
        report=walk_forward(self.rows,asof_utc=self.now)
        self.assertEqual(report['n'],6);self.assertIn('brier',report['conditional_ot_winner'])
        self.assertFalse(report['automatic_promotion']);self.assertFalse(report['live_market_admission'])
        captured_today=deepcopy(self.rows)
        for vs in captured_today:vs[0]['observed_at_utc']=self.now;vs[0]['ingested_at_utc']=self.now
        report=walk_forward(captured_today,asof_utc=self.now)
        self.assertEqual(report['n'],0);self.assertEqual(report['status'],'ABSTAIN_NO_TIME_VALID_OT_PAIRS')
