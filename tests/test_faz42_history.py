"""Synthetic chronological tests. Never real prematch performance evidence."""
from copy import deepcopy
from datetime import datetime,timezone
from unittest import TestCase
from unittest.mock import patch

import faz42_history as h
from faz41_adapters import capture
from faz41_evidence import REGISTRY,fixture_identity
from prediction_inputs import digest
from tests.test_faz32 import summary

NOW=1793960000


def permitted_registry():
    r=deepcopy(REGISTRY)
    for p in r.values():p.update(usage='PERMITTED',permission_ref='https://licence.example/synthetic-grant',
        reviewed_at_utc=NOW-40*86400,expires_at_utc=NOW+100*86400)
    return r


def history(registry=None,n=10):
    registry=registry or permitted_registry();observations=[]
    for i in range(n):
        start=NOW-(14-i)*86400;raw=summary(401900001+i,start,reverse=bool(i%2));raw.pop('boxscore',None)
        for t in raw['header']['competitions'][0]['competitors']:
            q=[21+i%3,22+i%4,24+i%2,26+i%5] if t['team']['id']=='19' else [20+i%4,23+i%2,21+i%3,25+i%4]
            t['linescores']=[{'displayValue':str(v),'value':v} for v in q];t['score']=str(sum(q))
        teams=raw['header']['competitions'][0]['competitors']
        if teams[0]['score']==teams[1]['score']:
            teams[0]['linescores'][0]['displayValue']=str(int(teams[0]['linescores'][0]['displayValue'])+1)
            teams[0]['linescores'][0]['value']+=1;teams[0]['score']=str(int(teams[0]['score'])+1)
        with patch('time.time',return_value=start+12000):
            observations.append(capture(raw,provider='ESPN',league='NBA',season_end_year=2027,
                observed_at_utc=start+10000,ingested_at_utc=start+11000,usage='SYNTHETIC_TEST',registry=registry,registry_pin=digest(registry)))
    return observations


class HistoricalTrackTests(TestCase):
    def setUp(self):
        self.clock=patch('time.time',return_value=NOW);self.timer=self.clock.start();self.addCleanup(self.clock.stop)
        self.registry=permitted_registry();self.pin=digest(self.registry);self.records=history(self.registry)
        self.target=self.records[-1]['payload']['fixture'];self.cutoff=self.target['start_utc']-1

    def inventory(self,records=None):
        return h.inventory(self.records if records is None else records,asof_utc=NOW,registry=self.registry,registry_pin=self.pin)

    def forecast(self,records=None,**options):
        args=dict(minimum_team_games=2,registry=self.registry,registry_pin=self.pin);args.update(options)
        return h.forecast(self.records if records is None else records,self.target,self.cutoff,**args)

    def evaluate(self,records=None,**options):
        starts=[p['payload']['fixture']['start_utc'] for p in self.records]
        args=dict(league='NBA',season_end_year=2027,train_end_utc=starts[3],validation_end_utc=starts[6],
            asof_utc=NOW,minimum_team_games=2,minimum_evaluation_games=2,registry=self.registry,registry_pin=self.pin)
        args.update(options);return h.evaluate(self.records if records is None else records,**args)

    def test_inventory_distinct_games_reobservations_and_missingness(self):
        r=self.inventory(self.records+[self.records[0]]);p=r['partitions']['NBA:2027']
        self.assertEqual(p['unique_games'],10);self.assertEqual(p['observations'],11)
        self.assertEqual(p['distinct_observation_digests'],10);self.assertEqual(p['period_games'],10)
        self.assertEqual(p['missing_player_minutes_games'],10);self.assertEqual(p['verified_lineup_stint_games'],0)
        for league in ('TBL','CBA','JAPAN','LEGA'):
            self.assertEqual(r['partitions'][league+':None']['status'],'ABSTAIN_NO_VERIFIED_ADAPTER')

    def test_unknown_permissions_are_inventory_only_and_force_abstention(self):
        registry=deepcopy(REGISTRY);records=history(registry)
        inv=h.inventory(records,asof_utc=NOW,registry=registry,registry_pin=digest(registry))
        self.assertEqual(inv['partitions']['NBA:2027']['usable_permission_games'],0)
        out=self.forecast(records,registry=registry,registry_pin=digest(registry))
        self.assertEqual(out['status'],'ABSTAIN');self.assertIsNone(out['prediction'])
        self.assertIn('SOURCE_USAGE_NOT_ESTABLISHED',out['excluded'])

    def test_real_clock_materialization_cannot_be_backfilled_for_old_targets(self):
        records=[]
        for o in self.records:
            p=o['payload'];records.append(capture(p['raw'],provider='ESPN',league='NBA',season_end_year=2027,
                observed_at_utc=p['observed_at_utc'],ingested_at_utc=NOW-1,usage='SYNTHETIC_TEST',registry=self.registry,registry_pin=self.pin))
        self.timer.return_value=NOW+1
        out=self.forecast(records);self.assertEqual(out['status'],'ABSTAIN');self.assertIsNone(out['prediction'])
        self.assertIn('UNAVAILABLE_AT_CUTOFF',out['excluded'])

    def test_chronology_train_validation_test_are_separate_and_period_metrics_exist(self):
        out=self.evaluate();self.assertEqual(out['cohorts']['VALIDATION']['games'],3);self.assertEqual(out['cohorts']['TEST']['games'],4)
        self.assertFalse(out['parameters_fitted']);self.assertFalse(out['hyperparameters_selected_on_test'])
        for role in ('VALIDATION','TEST'):
            self.assertEqual(set(out['cohorts'][role]['period_metrics']),set(h.PERIODS))
            self.assertIsNotNone(out['cohorts'][role]['metrics']['multiclass_brier'])
            self.assertIsNotNone(out['cohorts'][role]['metrics']['multiclass_log_loss'])

    def test_every_fold_uses_only_evidence_available_before_tipoff(self):
        out=self.evaluate();by_sha={o['sha256']:o['payload'] for o in self.records}
        for fold in out['folds']:
            for sha in fold['evidence_sha256']:
                p=by_sha[sha]
                self.assertLess(p['fixture']['start_utc'],fold['cutoff_utc'])
                for key in ('observed_at_utc','ingested_at_utc','materialized_at_utc'):self.assertLess(p[key],fold['cutoff_utc'])
            self.assertLess(fold['cutoff_utc'],fold['target']['start_utc'])

    def test_future_valid_labels_and_duplicate_games_do_not_change_projection(self):
        a=self.forecast();b=self.forecast(self.records[:-1])
        for key in ('prediction','simulation','evidence_sha256'):self.assertEqual(a[key],b[key])
        a=self.forecast();b=self.forecast(self.records+[self.records[0]])
        self.assertEqual(a['prediction'],b['prediction']);self.assertEqual(a['simulation'],b['simulation'])

    def test_small_realistic_sample_has_no_aggregate_metrics(self):
        out=self.evaluate(minimum_evaluation_games=30)
        self.assertIsNone(out['cohorts']['TEST']['metrics']);self.assertIsNone(out['cohorts']['TEST']['period_metrics'])
        self.assertEqual(out['status'],'ABSTAIN_INSUFFICIENT_EVALUATION_SAMPLE')

    def test_period_error_math_keeps_halves_and_regulation_consistent(self):
        p=dict(home=dict(quarters=[25.,26.,27.,28.]),away=dict(quarters=[20.,21.,22.,23.]))
        actual=dict(quarters_home=[24,25,26,27],quarters_away=[21,22,23,24])
        errors=h.period_errors(p,actual)
        self.assertEqual(errors['1Q'],dict(home=1.,away=-1.,total=0.,margin=2.))
        self.assertEqual(errors['1H']['margin'],4);self.assertEqual(errors['FULL']['margin'],8)

    def test_alias_fixture_collision_and_tampering_are_refused(self):
        x=deepcopy(self.records[0]);x['payload']['claims']['final_home']+=1;x['sha256']=digest(x['payload'])
        with self.assertRaisesRegex(ValueError,'CANNOT_REPLAY'):self.inventory([x])
        raw=deepcopy(self.records[0]['payload']['raw']);c=raw['header']['competitions'][0]
        raw['header']['id']=c['id']='401900099'
        for t in c['competitors']:
            if t['team']['id']=='2':t['team']['id']='8'
        start=self.records[0]['payload']['fixture']['start_utc']
        with patch('time.time',return_value=start+12000):
            y=capture(raw,provider='ESPN',league='NBA',season_end_year=2027,observed_at_utc=start+10000,
                ingested_at_utc=start+11000,usage='SYNTHETIC_TEST',registry=self.registry,registry_pin=self.pin)
        with self.assertRaisesRegex(ValueError,'SAME_TEAM_START'):self.inventory([self.records[0],y])

    def test_bad_splits_configuration_and_registry_pin_fail_closed(self):
        for opts in [dict(train_end_utc=NOW),dict(simulations=9999),dict(minimum_team_games=True),dict(registry_pin='0'*64)]:
            with self.subTest(opts=opts),self.assertRaises(ValueError):self.evaluate(**opts)
        self.assertEqual(self.evaluate(league='CBA')['status'],'ABSTAIN_NO_VERIFIED_ADAPTER')
