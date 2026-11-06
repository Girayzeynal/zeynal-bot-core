"""Synthetic research checks; never a real-match accuracy claim."""
from copy import deepcopy
import math
import unittest
from unittest.mock import patch

import faz40_archive as a
import faz40_research as r
from prediction_inputs import digest
from tests import test_faz32 as nba

NOW=1793944800


class ResearchEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.timer=patch('time.time',return_value=NOW);self.timer.start();self.addCleanup(self.timer.stop)
        self.records=[]
        for i in range(8):
            start=NOW-(14-i)*86400;raw=nba.summary(900020001+i,start,bool(i%2));raw.pop('boxscore',None)
            for side in raw['header']['competitions'][0]['competitors']:
                q=([20+i%3,23+i%4,24+i%2,25+i%5] if side['homeAway']=='home' else [22+i%4,20+i%3,22+i%5,24+i%4])
                side['linescores']=[dict(displayValue=str(v),value=v) for v in q];side['score']=str(sum(q))
            teams=raw['header']['competitions'][0]['competitors']
            if teams[0]['score']==teams[1]['score']:
                teams[0]['linescores'][0]['displayValue']=str(int(teams[0]['linescores'][0]['displayValue'])+1)
                teams[0]['linescores'][0]['value']+=1;teams[0]['score']=str(int(teams[0]['score'])+1)
            self.records.append(a.seal_game(raw,league='NBA',season_end_year=2027,
                source_observed_utc=start+10800,ingested_utc=start+14400,team_ids=['19','2'],usage='SYNTHETIC_TEST'))
        self.target=r.target_identity(self.records[-1]['payload']['facts'])
        self.cutoff=self.target['start_utc']-1

    def project(self,records=None,**changes):
        options=dict(mode='ARCHIVED_SOURCE_CLOCK',minimum_team_games=2,simulations=10000,seed=123)
        options.update(changes)
        return r.project(self.records if records is None else records,self.target,self.cutoff,**options)

    def test_four_quarters_halves_team_totals_margin_are_consistent(self):
        out=self.project();self.assertEqual(out['status'],'PROJECTED_RESEARCH')
        p=out['prediction']
        for side in ('home','away'):
            self.assertAlmostEqual(sum(p[side]['quarters']),p[side]['total'])
            self.assertAlmostEqual(p[side]['first_half']+p[side]['second_half'],p[side]['total'])
        self.assertAlmostEqual(p['total'],p['home']['total']+p['away']['total'])
        self.assertAlmostEqual(p['home_margin'],p['home']['total']-p['away']['total'])

    def test_10000_draws_are_seeded_and_three_regulation_events_sum_to_one(self):
        first=self.project();second=self.project()
        self.assertEqual(first,second)
        sim=first['simulation'];self.assertEqual(sim['simulations'],10000)
        self.assertAlmostEqual(sum(sim['probabilities']),1)
        self.assertEqual(first['scope'],'REGULATION_ONLY')
        self.assertEqual(first['calibration_status'],'NOT_ESTABLISHED')

    def test_synthetic_and_missing_player_pace_lineup_fields_stay_explicit(self):
        p=self.project();self.assertEqual(p['usage'],'SYNTHETIC_TEST')
        for tag in ['VERIFIED_PLAYER_MINUTES','LINEUP_STINTS','PLAY_BY_PLAY_GARBAGE_TIME','PACE_NOT_USED_IN_THIS_MODEL']:
            self.assertIn(tag,p['missing'])
        self.assertFalse(p['production_coefficients_changed'])

    def test_strict_materialization_clock_cannot_backfill_a_historical_forecast(self):
        p=self.project(mode='INGESTION_TIME')
        self.assertEqual(p['status'],'ABSTAIN_INSUFFICIENT_HISTORY');self.assertIsNone(p['simulation'])

    def test_future_valid_game_cannot_change_an_earlier_projection(self):
        self.assertEqual(self.project(self.records[:-1]),self.project(self.records))

    def test_schedule_spacing_and_halftime_features_are_descriptive(self):
        out=self.project();f=out['team_features']['home']['values']
        self.assertEqual(f['hours_since_previous_tipoff'],24)
        self.assertGreater(f['games_in_previous_7_days'],0)
        self.assertIsNotNone(f['second_half_delta_mean'])
        self.assertIsNotNone(f['opponent_scoring_form'])

    def test_alias_duplicates_cannot_increase_team_samples(self):
        before=self.project();after=self.project(self.records+[self.records[0]])
        self.assertEqual(before,after)

    def test_labels_cannot_be_passed_into_target_features(self):
        target=dict(self.target,actual_home=99)
        with self.assertRaisesRegex(ValueError,'LABELS'):
            r.project(self.records,target,self.cutoff)

    def test_low_simulation_count_and_invalid_correlation_fail(self):
        with self.assertRaisesRegex(ValueError,'10000'):self.project(simulations=9999)
        with self.assertRaises(ValueError):self.project(score_correlation=2)

    def test_walk_forward_keeps_self_and_future_results_out_of_features(self):
        result=r.walk_forward(self.records,league='NBA',season_end_year=2027,
                              mode='ARCHIVED_SOURCE_CLOCK',minimum_team_games=2,minimum_evaluation_games=2)
        self.assertGreater(result['evaluated_games'],0)
        starts={x['payload']['facts']['canonical_id']:x['payload']['facts']['start_utc'] for x in self.records}
        for fold in result['folds']:
            self.assertNotIn(fold['canonical_id'],fold['source_game_ids'])
            self.assertTrue(all(starts[cid]<fold['cutoff_utc'] for cid in fold['source_game_ids']))
        self.assertFalse(result['parameters_fitted']);self.assertEqual(result['prospective_records_created'],0)
        self.assertEqual(result['usage'],'SYNTHETIC_TEST')

    def metric_rows(self):
        return [dict(canonical_id=digest(i),league='NBA',season_end_year=2027,model=r.MODEL,
                    scope='REGULATION_ONLY',usage='SYNTHETIC_TEST',expected_home=100.,expected_away=100.,
                    actual_home=100,actual_away=100,probabilities=[.2,.3,.5],
                    cutoff_utc=100,start_utc=101,result_observed_utc=102) for i in range(2)]

    def test_regulation_tie_brier_logloss_and_error_metrics_have_correct_targets(self):
        out=r.metrics(self.metric_rows(),minimum_games=2)
        self.assertAlmostEqual(out['multiclass_brier'],.2**2+.3**2+.5**2)
        self.assertAlmostEqual(out['multiclass_log_loss'],-math.log(.5))
        self.assertEqual(out['total_mae'],0);self.assertEqual(out['margin_rmse'],0)
        self.assertFalse(out['statistical_superiority_claimed'])

    def test_small_samples_have_no_aggregate_metrics(self):
        self.assertIsNone(r.metrics(self.metric_rows()))

    def test_empty_archive_does_not_hide_invalid_configuration(self):
        for opts in [dict(simulations=9999),dict(mode='LIVE'),dict(minimum_team_games=True),dict(league='TBL')]:
            args=dict(league='NBA',season_end_year=2027);args.update(opts)
            with self.subTest(opts=opts),self.assertRaises(ValueError):r.walk_forward([],**args)

    def test_zero_observed_variance_is_abstention_not_an_invented_floor(self):
        records=[]
        for original in self.records:
            p=original['payload'];raw=deepcopy(p['raw'])
            for team in raw['header']['competitions'][0]['competitors']:
                value=20 if team['team']['id']=='19' else 21
                team['linescores']=[dict(displayValue=str(value),value=value) for _ in range(4)]
                team['score']=str(value*4)
            records.append(a.seal_game(raw,league='NBA',season_end_year=2027,source_observed_utc=p['source_observed_utc'],
                ingested_utc=p['ingested_utc'],team_ids=p['team_ids'],usage='SYNTHETIC_TEST'))
        result=self.project(records)
        self.assertEqual(result['status'],'ABSTAIN_DEGENERATE_VARIANCE');self.assertIsNone(result['simulation'])

    def test_duplicate_mixed_scope_league_usage_and_nonfinite_metrics_are_refused(self):
        base=self.metric_rows()
        variants=[]
        p=deepcopy(base);p[1]['canonical_id']=p[0]['canonical_id'];variants.append(p)
        for key,value in [('scope','FINAL_WITH_OT'),('league','EUROLEAGUE'),('usage','RETROSPECTIVE_RESEARCH'),('expected_home',float('nan')),('probabilities',[.5,.6,.1]),('cutoff_utc',101)]:
            p=deepcopy(base);p[1][key]=value;variants.append(p)
        for rows in variants:
            with self.subTest(row=rows[1]),self.assertRaises(ValueError):r.metrics(rows,minimum_games=2)


if __name__=='__main__':unittest.main()
