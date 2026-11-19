"""Real captured finals + synthetic native-model/transport regression tests.

Synthetic fitted accuracy is never external Telegram delivery or real superiority.
"""
import asyncio
from copy import deepcopy
from datetime import datetime,timezone
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
from unittest import TestCase,IsolatedAsyncioTestCase
from unittest.mock import Mock,patch

import numpy as np

from core.team_identity import digest
from hybrid_engine import nba_dynamic,shadow_learning
from hybrid_engine import nba_schedule_features as schedule
from hybrid_engine.data import metadata,Abstain
from hybrid_engine.issue90_research import Research,run_serial,status
from hybrid_engine.joint_market_audit import audit as market_audit
from hybrid_engine.nba_failure_audit import review,CASES
from hybrid_engine.result_poll import poll_once
from hybrid_engine.results_health import inspect,render
from hybrid_engine.boxes import checked_stats
from hybrid_engine.decision_layer import QuoteEvidence,RuleEvidence
from hybrid_engine.distributions import Forecast
from tests.test_adaptive_research import cohort
from tests.test_handoff_hardening import snapshot_ledger
from tests.test_season_archive_audit import nba,NOW,START

ROOT=Path(__file__).resolve().parents[1]


def captured():
    with gzip.open(ROOT/'docs/evidence/issue90-native-20261118.json.gz','rt') as f:w=json.load(f)
    if digest(w['payload'])!=w['sha256']:raise ValueError('REAL_CAPTURE_PIN')
    return w['payload']


class NativeFiveGameTests(TestCase):
    def test_real_receipts_prove_five_finals_but_not_missing_original_archive(self):
        receipt=captured()['receipts'][0];r=review(receipt)
        self.assertEqual(len(r['cases']),5);self.assertFalse(r['forecasts_created'])
        for c in r['cases']:
            self.assertEqual(c['status'],'ESPN_FINAL_VERIFIED_NBA_AUTHORITY_NOT_VERIFIED')
            self.assertFalse(c['live_performance_eligible']);self.assertEqual(c['forecasts'],[])
        self.assertEqual(r['nba_official_verification'],'NOT_VERIFIED')

    def test_lakers_regulation_222_and_ot_final_232_are_separate(self):
        row=next(c for c in review(captured()['receipts'][0])['cases'] if c['provider_fixture_id']=='401910005')
        self.assertEqual(row['regulation_scores'],[111,111]);self.assertEqual(row['final_with_ot'],[118,114])
        self.assertTrue(row['overtime']);self.assertEqual(row['regulation_total'],222)

    def test_each_summary_independently_agrees_with_scoreboard_periods(self):
        p=captured();r=review(p['receipts'][0])
        for row,receipt in zip(r['cases'],p['receipts'][1:]):
            self.assertEqual(receipt['document_sha256'],digest(receipt['document']))
            g=receipt['document']['header']['competitions'][0]
            self.assertEqual(g['id'],row['provider_fixture_id'])
            for s in ('home','away'):
                native=next(t for t in g['competitors'] if t['homeAway']==s)
                self.assertEqual([int(float(v.get('displayValue',v.get('value')))) for v in native['linescores']],row['periods'][s])

    def test_missing_event_stays_missing_not_zero_error(self):
        r=deepcopy(captured()['receipts'][0]);r['document']['events']=[e for e in r['document']['events'] if e['id']!=CASES[0][0]]
        r['document_sha256']=digest(r['document'])
        out=review(r)['cases'][0];self.assertEqual(out['status'],'MISSING_FINAL');self.assertFalse(out['live_performance_eligible'])

    def test_wrong_team_date_hash_and_official_boolean_are_rejected(self):
        original=captured()['receipts'][0]
        for change in ('team','date','hash','authority'):
            r=deepcopy(original)
            if change=='team':r['document']['events'][0]['competitions'][0]['competitors'][0]['team']['id']='999'
            elif change=='date':r['document']['events'][0]['date']='2026-11-20T00:30Z'
            elif change=='hash':r['document_sha256']='a'*64
            if change in ('team','date'):r['document_sha256']=digest(r['document'])
            with self.subTest(change=change),self.assertRaises(ValueError):review(r,official_verified=change=='authority')


class DynamicModelTests(TestCase):
    def setUp(self):
        self.rows=cohort(85);self.now=self.rows[70][0]['fixture_start_utc']-1800
        timer=patch('time.time',return_value=self.now);timer.start();self.addCleanup(timer.stop)
        self.target=metadata(self.rows[71][0]);self.artifact=nba_dynamic.fit(self.rows,cutoff_utc=self.now)

    def test_recent_full_game_efficiency_changes_mean(self):
        old=nba_dynamic.predict(self.artifact,self.target,cutoff_utc=self.now)
        changed=deepcopy(self.rows)
        for version in changed[50:70]:
            r=version[0]
            for j,s in enumerate(('home','away')):
                b=r['box']['teams'][s];b['fgm2']+=8;b['points']+=16;r['final_scores'][j]+=16
                r['periods'][s]=[v+4 for v in r['periods'][s]];b.update(checked_stats(b))
        artifact=nba_dynamic.fit(changed,cutoff_utc=self.now);new=nba_dynamic.predict(artifact,self.target,cutoff_utc=self.now)
        self.assertGreater(sum(new.scores),sum(old.scores)+5)
        self.assertTrue(new.metadata['dynamic_full_game_mean']);self.assertTrue(new.metadata['opponent_adjusted'])

    def test_future_labels_cannot_change_parameters_or_paths(self):
        changed=deepcopy(self.rows)
        for version in changed[70:]:version[0]['periods']['home']=[99]*4
        artifact=nba_dynamic.fit(changed,cutoff_utc=self.now)
        self.assertEqual(artifact,self.artifact)
        self.assertNotIn(self.target['fixture_id'],artifact['payload']['training_ids'])

    def test_mc_and_rqmc_generate_full_rank_stochastic_joint_quarters(self):
        rq=nba_dynamic.predict(self.artifact,self.target,cutoff_utc=self.now)
        mc=nba_dynamic.predict(self.artifact,self.target,cutoff_utc=self.now,method='MC')
        for f in (rq,mc):
            self.assertEqual(f.samples.shape,(10000,4,2));self.assertEqual(np.linalg.matrix_rank(np.cov(f.samples.reshape(-1,8).T)),8)
            self.assertFalse(f.metadata['deterministic_period_allocation']);self.assertTrue(f.metadata['parameter_uncertainty_integrated'])
            self.assertAlmostEqual(sum(f.probabilities()),1)
        np.testing.assert_allclose(rq.samples.mean(axis=0),mc.samples.mean(axis=0),atol=.5)
        self.assertEqual(rq.metadata['method'],'RQMC_HALTON_8D')

    def test_box_estimate_is_never_labeled_measured_pbp(self):
        f=nba_dynamic.predict(self.artifact,self.target,cutoff_utc=self.now)
        self.assertFalse(f.metadata['measured_pbp']);self.assertFalse(f.metadata['player_effects'])
        with self.assertRaisesRegex(Abstain,'NOT_VERIFIED'):nba_dynamic.predict(self.artifact,self.target,cutoff_utc=self.now,require_all_features=True)

    def test_missing_boxes_stale_history_and_cross_league_refuse(self):
        rows=deepcopy(self.rows)
        for v in rows:v[0].pop('box')
        with self.assertRaisesRegex(Abstain,'THIRTY_NATIVE'):nba_dynamic.fit(rows,cutoff_utc=self.now)
        for league in ('EuroLeague','EuroCup'):
            rows=cohort(85,league)
            with self.assertRaisesRegex(ValueError,'NBA_ONLY'):nba_dynamic.fit(rows,cutoff_utc=self.now)
        with patch('time.time',return_value=self.now+30*86400),self.assertRaisesRegex(Abstain,'RECENT_TEAM'):
            nba_dynamic.predict(self.artifact,dict(self.target,fixture_start_utc=self.now+31*86400),cutoff_utc=self.now+30*86400)

    def test_mutated_pin_training_target_and_final_fifteen_minutes_fail_closed(self):
        changed=deepcopy(self.artifact);changed['payload']['coefficients'][0]+=1
        with self.assertRaisesRegex(ValueError,'PIN'):nba_dynamic.predict(changed,self.target,cutoff_utc=self.now)
        with self.assertRaisesRegex(ValueError,'TARGET_TRAINING'):nba_dynamic.predict(self.artifact,dict(self.target,fixture_id='1'),cutoff_utc=self.now)
        for offset in (899,0,-60):
            with self.subTest(offset=offset),self.assertRaisesRegex(Abstain,'PREMATCH_CLOCK'):
                nba_dynamic.predict(self.artifact,dict(self.target,fixture_start_utc=self.now+offset),cutoff_utc=self.now)


def shadow_audit(n=120,now=1794900000):
    rows=[];native=[]
    for i in range(n):
        start=now-(n-i)*86400;fid=str(i);pin=digest(dict(fixture=fid))
        r=dict(fixture_id=fid,league='NBA',season='2026/2027',model_version='SYNTHETIC_TEST',model_digest='a'*64,
            snapshot_sha256=pin,prediction_generated_at_utc=start-3600,first_archived_at_utc=start-3599,
            fixture_start_utc=start,label_available_utc=start+7200,winner=[.8,.05,.15],actual=[100,110])
        rows.append(r);native.append(dict(fixture_id=fid,model_digest='a'*64,findings=[],
            source_audit=dict(status='VERIFIED_WITH_LIMITATIONS',snapshot_sha256=pin),
            calibration_inputs=dict(inputs_available_max_utc=start-3601,model_fit_cutoff_utc=start-7200,model_training_ids=[])))
    return dict(observed_at_utc=now,performance=dict(forecasts=rows),rows=native)


class ShadowLearningTests(TestCase):
    def setUp(self):
        self.now=1794900000;timer=patch('time.time',return_value=self.now);timer.start();self.addCleanup(timer.stop)
        self.audit=shadow_audit(now=self.now);self.c=shadow_learning.fit(self.audit,model_digest='a'*64,season='2026/2027')
        self.row=dict(fixture_id='future',league='NBA',season='2026/2027',model_digest='a'*64,
            snapshot_sha256='f'*64,winner=[.8,.05,.15],fixture_start_utc=self.now+7200)

    def test_past_fits_produce_separate_future_calibration_not_active_updates(self):
        before=deepcopy(self.audit);p=shadow_learning.apply(self.c,self.row,generated_at_utc=self.now)
        self.assertGreater(p['candidate'][2],.95);self.assertEqual(self.audit,before)
        self.assertEqual(p['raw'],[.8,.05,.15]);self.assertIsNone(p['confidence_index'])
        self.assertFalse(self.c['payload']['production_enabled'])

    def test_hundred_independent_native_rows_and_exact_source_scope_required(self):
        bad=deepcopy(self.audit)
        for n in bad['rows'][:21]:n['findings']=['UNVERIFIED']
        with self.assertRaisesRegex(Abstain,'HUNDRED_NATIVE'):shadow_learning.fit(bad,model_digest='a'*64,season='2026/2027')
        for key,value in (('season','OTHER'),('model_digest','b'*64),('fixture_id','1')):
            with self.subTest(key=key),self.assertRaises(Abstain):shadow_learning.apply(self.c,dict(self.row,**{key:value}),generated_at_utc=self.now)

    def test_training_overlap_future_label_and_after_fit_target_are_refused(self):
        bad=deepcopy(self.audit);bad['performance']['forecasts'][0]['label_available_utc']=self.now+1
        with self.assertRaisesRegex(ValueError,'TRAINING_CLOCK'):shadow_learning.fit(bad,model_digest='a'*64,season='2026/2027')
        with self.assertRaisesRegex(Abstain,'FUTURE_PUBLICATION'):shadow_learning.apply(self.c,self.row,generated_at_utc=self.now-1)

    def _future(self,n=100,correct=True):
        pubs=[];labels=[]
        for i in range(n):
            start=self.now+(i+1)*86400;row=dict(self.row,fixture_id='future'+str(i),fixture_start_utc=start,snapshot_sha256=digest(dict(i=i)))
            p=shadow_learning.apply(self.c,row,generated_at_utc=self.now);pubs.append(p)
            labels.append(dict(row,actual=[100,110] if correct else [110,100],label_available_utc=start+7200))
        return pubs,labels

    def test_unseen_future_improvement_and_rejection_are_both_enforced(self):
        for correct in (True,False):
            pubs,labels=self._future(correct=correct)
            with patch('time.time',return_value=self.now+102*86400):r=shadow_learning.evaluate(pubs,labels,registered_at_utc=self.now)
            self.assertEqual(r['n'],100);self.assertEqual(r['days'],100)
            self.assertEqual(r['status'],'CANDIDATE_FOR_MANUAL_REVIEW' if correct else 'REJECTED_NO_VERIFIED_IMPROVEMENT')
            self.assertFalse(r['automatic_promotion']);self.assertFalse(r['production_enabled'])

    def test_missing_wrong_snapshot_and_duplicate_labels_do_not_create_success(self):
        pubs,labels=self._future(1)
        with patch('time.time',return_value=self.now+3*86400):
            r=shadow_learning.evaluate(pubs,[dict(labels[0],snapshot_sha256='wrong')],registered_at_utc=self.now)
            self.assertEqual(r['n'],0)
            with self.assertRaisesRegex(ValueError,'DUPLICATE'):shadow_learning.evaluate(pubs*2,labels,registered_at_utc=self.now)
            with self.assertRaisesRegex(ValueError,'EXACT_NATIVE_LABEL'):shadow_learning.evaluate(pubs,labels*2,registered_at_utc=self.now)


class ResultHealthTests(IsolatedAsyncioTestCase):
    async def test_unreadable_native_archive_is_visible_without_crashing_diagnostics(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'broken.sqlite';p.write_bytes(b'NOT_A_DATABASE')
            r=inspect(p);self.assertEqual(r['status'],'ARCHIVE_NOT_VERIFIED')
            self.assertNotIn('settled_forecasts',r);self.assertEqual(p.read_bytes(),b'NOT_A_DATABASE')
    async def test_incomplete_source_and_abstention_are_not_green_checks(self):
        journal=SimpleNamespace(append=Mock())
        r=await poll_once([('LIVE_NBA',lambda:dict(status='SOURCE_INCOMPLETE')),('OTHER',lambda:dict(status='BLOCKED')),('NEXT',lambda:dict(settled=2))],journal)
        self.assertEqual(r['LIVE_NBA']['status'],'SOURCE_INCOMPLETE');self.assertEqual(r['OTHER']['status'],'ABSTAIN');self.assertEqual(r['NEXT']['status'],'CHECKED')
        self.assertIsInstance(r['NEXT']['completed_at_utc'],int)

    async def test_health_separates_started_from_final_without_any_database_write(self):
        with TemporaryDirectory() as tmp:
            ledger=snapshot_ledger(Path(tmp)/'ledger.sqlite',[nba()]);before=ledger.path.read_bytes()
            with patch('time.time',return_value=NOW):r=inspect(ledger.path)
            self.assertEqual(r['pending_started_fixtures'],1);self.assertEqual(r['settled_forecasts'],0)
            self.assertEqual(r['status'],'PENDING_STARTED_RESULTS');self.assertEqual(before,ledger.path.read_bytes())
            self.assertIn('doğrulanmış final eksik',render(r))


def quote(market,line=0.,period='FULL',price=1.9):
    p=dict(format='EXPLICIT_BOOK_MARKET_V1',league='NBA',season='SYNTHETIC',fixture_id='future',
        home_team_id='1',away_team_id='2',tipoff_utc=1795000000,bookmaker_id='SYNTHETIC_TEST',period=period,
        market=market,line=line,prices=dict(over=price,under=price),observed_at_utc=1794900000,ingested_at_utc=1794900000)
    return QuoteEvidence(p,digest(p))


def rule(q,ot=False):
    p=dict(format='EXPLICIT_BOOK_SETTLEMENT_V1',league='NBA',bookmaker_id='SYNTHETIC_TEST',period=q.payload['period'],market=q.payload['market'],
        include_overtime=ot,stake_rule='WHOLE_STAKE_WIN_LOSS_PUSH',tie_policy='PUSH',effective_from_utc=1794800000,effective_until_utc=None,
        observed_at_utc=1794900000,ingested_at_utc=1794900000)
    return RuleEvidence(p,digest(p))


class JointMarketsTests(TestCase):
    def setUp(self):
        timer=patch('time.time',return_value=1795020000);timer.start();self.addCleanup(timer.stop)
        # Exactly dependent outcomes: every home win is also OVER.
        paths=np.asarray([[[30,25]]*4]*5000+[[[20,25]]*4]*5000,dtype=np.int32)
        self.f=Forecast('SYNTHETIC',paths.mean(axis=0),samples=paths)
        self.trace=dict(fixture_id='future',league='NBA',season='SYNTHETIC',home_team_id='1',away_team_id='2',
            tipoff_utc=1795000000,inputs_available_max_utc=1794899999,prediction_utc=1794900001,
            model_digest='a'*64,snapshot_sha256='b'*64)

    def test_joint_probability_uses_intersection_point_five_not_product_point_two_five(self):
        qs=[quote('WINNER'),quote('TOTAL',200.5)]
        r=market_audit(self.f,self.trace,qs,asof_utc=1794900002)
        self.assertEqual(r['joint'][0]['raw_regulation_joint_probabilities']['home_over'],.5)
        self.assertIsNone(r['joint'][0]['expected_value']);self.assertIsNone(r['joint'][0]['calibrated_joint_probabilities'])

    def test_all_market_periods_settle_on_same_paths_with_verified_scope(self):
        qs=[quote(k,line,p) for k,line,p in [('WINNER',0,'FULL'),('HOME_HANDICAP',-2,'FULL'),('TOTAL',200,'FULL'),
            ('HOME',100,'FULL'),('AWAY',100,'FULL'),('TOTAL',100,'1H')]+[('TOTAL',50,str(q)+'Q') for q in range(1,5)]]
        final=dict(fixture_id='future',snapshot_sha256='b'*64,model_digest='a'*64,fixture_start_utc=1795000000,
            label_available_utc=1795010000,actual_periods=dict(home=[30]*4,away=[25]*4))
        r=market_audit(self.f,self.trace,qs,rules={q.sha256:rule(q) for q in qs},asof_utc=1795010001,final=final)
        self.assertEqual(len(r['markets']),10)
        for m in r['markets']:self.assertIsNotNone(m['raw_probabilities']);self.assertIsNotNone(m['realized'])

    def test_no_quotes_stale_post_forecast_or_overtime_rules_never_invent_edge(self):
        self.assertEqual(market_audit(self.f,self.trace,asof_utc=1794900002)['status'],'NO_MARKET_DATA')
        q=quote('TOTAL',200)
        for q2,rules in [(q,{}),(q,{q.sha256:rule(q,True)})]:
            r=market_audit(self.f,self.trace,[q2],rules=rules,asof_utc=1794900002)['markets'][0]
            self.assertIsNone(r['expected_value'])
        changed=deepcopy(q.payload);changed['observed_at_utc']-=600
        r=market_audit(self.f,self.trace,[QuoteEvidence(changed,digest(changed))],asof_utc=1794900002)
        self.assertIsNone(r['markets'][0]['raw_probabilities']);self.assertFalse(r['joint'])

    def test_wrong_final_snapshot_model_and_non_full_overtime_are_rejected(self):
        q=quote('TOTAL',200);final=dict(fixture_id='future',snapshot_sha256='wrong',model_digest='a'*64,
            fixture_start_utc=1795000000,label_available_utc=1795010000,actual_periods=dict(home=[25]*4,away=[25]*4))
        with self.assertRaisesRegex(ValueError,'FINAL_FIXTURE'):market_audit(self.f,self.trace,[q],asof_utc=1795010001,final=final)
        q=quote('TOTAL',50,'1Q')
        with self.assertRaisesRegex(Abstain,'NON_FULL_OVERTIME'):market_audit(self.f,self.trace,[q],rules={q.sha256:rule(q,True)},asof_utc=1794900002)


class ProductionResultPathTests(TestCase):
    def test_real_sqlite_result_ingestion_preserves_every_original_snapshot(self):
        from hybrid_engine.production_results import collect
        from tests.test_handoff_hardening import receipt
        from ledger_reports import LedgerReports
        import sqlite3
        with TemporaryDirectory() as tmp:
            ledger=snapshot_ledger(Path(tmp)/'isolated.sqlite',[nba()])
            def originals():
                with sqlite3.connect(ledger.path) as db:return db.execute('SELECT payload,sha256 FROM live_analysis_snapshots ORDER BY fixture_id').fetchall()
            before=originals()
            with patch('time.time',return_value=NOW):
                r=collect(SimpleNamespace(ledger=ledger),fetcher=lambda p,u:receipt(dict(events=[nba()]),u))
            self.assertEqual(r['status'],'CHECKED');self.assertEqual(r['pending'],0);self.assertEqual(originals(),before)
            report=LedgerReports(ledger.path).read('NBA')
            self.assertEqual(report['forecasts'][0]['actual'],[115,109])
    def test_disabled_missing_release_and_missing_ledger_make_no_source_calls(self):
        from hybrid_engine.production_results import collect
        fetch=Mock(side_effect=AssertionError('NO NETWORK'))
        for service in (None,SimpleNamespace(configuration_error='RELEASE_SHA_NOT_CONFIGURED'),SimpleNamespace(ledger=None,ledger_factory=lambda:None)):
            self.assertEqual(collect(service,fetcher=fetch)['status'],'ABSTAIN')
        fetch.assert_not_called()

    def test_verified_service_uses_its_own_exact_ledger_not_replay_or_default_path(self):
        from hybrid_engine.production_results import collect
        ledger=object();fetch=Mock();service=SimpleNamespace(ledger=ledger,configuration_error=None)
        with patch('hybrid_engine.production_results.settle',return_value=dict(status='SOURCE_INCOMPLETE')) as settle:
            r=collect(service,fetcher=fetch)
        settle.assert_called_once_with(ledger,fetcher=fetch);self.assertEqual(r['status'],'SOURCE_INCOMPLETE')


class Issue90ForwardTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.rows=cohort(85);self.now=self.rows[70][0]['fixture_start_utc']-1800
        timer=patch('time.time',side_effect=lambda:self.now);timer.start();self.addCleanup(timer.stop)
        target=dict(metadata(self.rows[71][0]),provider_fixture_ids=['401123456'])
        self.original=dict(model_digest='a'*64,prediction=dict(winner=[.6,.1,.3]))
        model=nba_dynamic.fit(self.rows,cutoff_utc=self.now);forecast=nba_dynamic.predict(model,target,cutoff_utc=self.now)
        self.case=dict(target=target,original=digest(self.original),snapshot=self.original,
            frozen=dict(status='FORECAST_CREATED',prediction=forecast.summary()),code='NBA')
        self.worker=SimpleNamespace(cases=lambda:[self.case],store=SimpleNamespace(cohort=lambda *args:self.rows),
            verify=lambda t:dict(ingested_at_utc=self.now),labels=lambda:[],nba=SimpleNamespace(ledger=SimpleNamespace(path='UNAVAILABLE'),assets='UNAVAILABLE'))
        self.study=Research(Path(self.tmp.name)/'v3',self.worker);self.model=model;self.plan=self.study.plan()

    def test_duplicate_retry_and_restart_preserve_first_candidate(self):
        self.study.admit(self.case,self.plan)
        a,new=self.study.capture(self.case,self.model,self.plan);self.assertTrue(new)
        self.now+=1
        b,new=self.study.capture(self.case,self.model,self.plan);self.assertFalse(new);self.assertEqual(a,b)
        restarted=Research(self.study.root,self.worker);c,new=restarted.capture(self.case,self.model,restarted.plan())
        self.assertFalse(new);self.assertEqual(a,c);self.assertEqual(len(restarted.registry.records()),1)

    def test_verify_crosses_final_fifteen_minutes_no_first_record(self):
        def cross(target):self.now=target['fixture_start_utc']-899;return dict(ingested_at_utc=self.now)
        self.worker.verify=cross
        with self.assertRaisesRegex(Abstain,'WINDOW_CLOSED'):self.study.capture(self.case,self.model,self.plan)
        self.assertEqual(self.study.registry.records(),[])

    def test_changed_plan_never_resets_existing_study(self):
        with patch('hybrid_engine.issue90_research.pins',return_value={}):
            with self.assertRaisesRegex(ValueError,'NEW_STUDY'):self.study.plan()

    def test_settlement_metrics_require_exact_original_sha_and_regulation(self):
        self.study.admit(self.case,self.plan);p,_=self.study.capture(self.case,self.model,self.plan)
        t=self.case['target'];self.now=t['fixture_start_utc']+7200
        label=dict(fixture_id=t['fixture_id'],snapshot_sha256=self.case['original'],model_digest='a'*64,
            model_version='SYNTHETIC',season=t['season'],league='NBA',fixture_start_utc=t['fixture_start_utc'],label_available_utc=self.now,
            prediction=[110.,110.],actual=[100,100],actual_periods=dict(home=[25,25,25,25,9],away=[25,25,25,25,6]),
            predicted_quarters=[[27.5,27.5]]*4,winner=[.4,.2,.4],prediction_generated_at_utc=t['fixture_start_utc']-3600,intervals=None)
        r=self.study.performance([label],self.plan)
        self.assertEqual(r['matched'],1);self.assertEqual(r['candidate']['n'],1);self.assertIn('winner',r['candidate']);self.assertIn('coverage',r['candidate'])
        self.assertEqual(r['baseline']['total']['mae'],20);self.assertEqual(r['gate'],'ABSTAIN_INSUFFICIENT_FUTURE_EVIDENCE')
        self.assertEqual(self.study.performance([dict(label,snapshot_sha256='wrong')],self.plan)['matched'],0)

    def test_dynamic_primary_gate_tests_hundred_unseen_days_not_training_scores(self):
        self.study.admit(self.case,self.plan);template,_=self.study.capture(self.case,self.model,self.plan)
        labels=[]
        # Synthetic evaluation-only publications; these are not native live data.
        for i in range(100):
            t=dict(self.case['target'],fixture_id='future-'+str(i),fixture_start_utc=self.now+(i+2)*86400)
            c=dict(self.case,target=t,original=digest(dict(synthetic=i)))
            self.study.admit(c,self.plan)
            p=deepcopy(template);p['fixture'].update(t,canonical_id=t['fixture_id'],start_ts_utc=t['fixture_start_utc'])
            p['original_snapshot_sha256']=c['original'];p['candidate'].update(home=100.,away=100.,total=200.,margin=0.,quarters=[[25.,25.]]*4,halves=[[50.,50.]]*2)
            self.study.registry.record(p)
            labels.append(dict(fixture_id=t['fixture_id'],snapshot_sha256=c['original'],model_digest='a'*64,
                model_version='SYNTHETIC',season=t['season'],league='NBA',fixture_start_utc=t['fixture_start_utc'],
                label_available_utc=t['fixture_start_utc']+7200,prediction=[110.,110.],predicted_quarters=[[27.5,27.5]]*4,
                actual=[100,100],actual_periods=dict(home=[25]*4,away=[25]*4),winner=[.4,.2,.4],intervals=None,
                prediction_generated_at_utc=self.now))
        self.now+=103*86400;r=self.study.performance(labels,self.plan)
        self.assertEqual(r['matched'],100);self.assertEqual(r['gate'],'CANDIDATE_FOR_MANUAL_REVIEW')
        self.assertLess(r['paired']['metrics']['team_mae']['interval'][1],0)
        self.assertFalse(r['production_enabled']);self.assertFalse(r['automatic_promotion'])

    def test_status_does_not_create_missing_directory_or_register_plan(self):
        path=Path(self.tmp.name)/'absent';r=status(path)
        self.assertEqual(r['status'],'NO_RECORDED_ATTEMPT');self.assertFalse(path.exists())

    def test_calibration_capture_is_independent_of_box_model_readiness(self):
        candidate=shadow_learning.fit(shadow_audit(now=self.now),model_digest='a'*64,season='2026/2027')
        # Use the synthetic candidate's own bin and exact cohort.
        self.case['target']['season']='2026/2027';self.case['snapshot']['prediction']['winner']=[.8,.05,.15]
        self.case['target']['fixture_id']='future-independent';self.case['original']=digest(self.case['snapshot'])
        with patch('hybrid_engine.issue90_research.audit_ledger',return_value=shadow_audit(now=self.now)),\
             patch.object(self.study,'fit',side_effect=Abstain('DYNAMIC_THIRTY_NATIVE_BOX_GAMES_REQUIRED')):
            r=self.study.tick()
        self.assertEqual(r['captures'][0]['status'],'ABSTAIN')
        self.assertEqual(r['shadow_captures'][0]['status'],'ARCHIVED')
        self.assertEqual(len(self.study.shadow_registry.records()),1)


class SerialWorkerTests(IsolatedAsyncioTestCase):
    async def test_v3_runs_after_v2_and_cancellation_propagates(self):
        order=[]
        async def tick():order.append('v2');return dict(status='CHECKED')
        def v3():order.append('v3');return dict(status='ABSTAIN')
        app=SimpleNamespace(bot_data={});task=asyncio.create_task(run_serial(SimpleNamespace(tick=tick),SimpleNamespace(tick=v3),app))
        for _ in range(100):
            await asyncio.sleep(.001)
            if 'last_issue90_poll' in app.bot_data:break
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(order,['v2','v3']);self.assertEqual(app.bot_data['last_issue90_poll']['status'],'ABSTAIN')


class ScheduleContextTests(TestCase):
    def setUp(self):
        self.now=1794900000;self.start=self.now+7200
        timer=patch('time.time',return_value=self.now);timer.start();self.addCleanup(timer.stop)
        from season_archive_inventory import archive_catalog
        event=nba('401123456');event['date']=datetime.fromtimestamp(self.start,timezone.utc).isoformat()
        event['status']=event['competitions'][0]['status']=dict(type=dict(state='pre',completed=False,name='STATUS_SCHEDULED'))
        for t in event['competitions'][0]['competitors']:t['score']='0';t.pop('linescores')
        event['competitions'][0]['venue']=dict(location=dict(latitude=40.,longitude=-70.))
        previous=nba('401123455');previous['date']=datetime.fromtimestamp(self.start-86400,timezone.utc).isoformat()
        previous['competitions'][0]['venue']=dict(location=dict(latitude=42.,longitude=-75.))
        c=archive_catalog(dict(events=[event]),provider='ESPN',season_start_year=2026,observed_at_utc=self.now,ingested_at_utc=self.now)
        g=c['payload']['fixtures'][0]
        self.target=dict(league='NBA',season='2026/2027',fixture_id=g['canonical_id'],fixture_start_utc=self.start,
            home_team_id='1',away_team_id='2',provider_fixture_ids=['401123456'])
        self.receipts=[]
        for i,url in enumerate(schedule.urls(self.target)):
            doc=dict(events=[event] if i==0 else [previous] if i==1 else [])
            self.receipts.append(dict(provider='ESPN',source_url=url,status='DOCUMENT_RECEIVED',http_status=200,
                document=doc,document_sha256=digest(doc),observed_at_utc=self.now,ingested_at_utc=self.now))

    def test_native_calendar_gap_b2b_and_venue_distance_keep_proxy_scope(self):
        c=schedule.capture(self.target,self.receipts)['payload']
        for s in ('home','away'):
            self.assertEqual(c['values'][s]['start_gap_hours'],24);self.assertTrue(c['values'][s]['back_to_back_calendar_days'])
            self.assertGreater(c['values'][s]['venue_geodesic_km'],100)
        self.assertFalse(c['actual_itinerary_observed']);self.assertFalse(c['physiological_rest_measured'])

    def test_incomplete_calendar_missing_coordinates_and_late_capture_never_fill_zero(self):
        with self.assertRaisesRegex(Abstain,'EIGHT_NATIVE'):schedule.capture(self.target,self.receipts[:2])
        changed=deepcopy(self.receipts)
        for r in changed:
            for e in r['document']['events']:e['competitions'][0].pop('venue',None)
            r['document_sha256']=digest(r['document'])
        c=schedule.capture(self.target,changed)['payload']
        self.assertIsNone(c['values']['home']['venue_geodesic_km'])
        with patch('time.time',return_value=self.start-899),self.assertRaisesRegex(Abstain,'PREMATCH_WINDOW'):
            schedule.capture(self.target,self.receipts)

    def test_hash_tampering_and_future_receipt_are_refused(self):
        for key in ('document_sha256','ingested_at_utc'):
            changed=deepcopy(self.receipts);changed[0][key]='wrong' if key=='document_sha256' else self.now+1
            with self.subTest(key=key),self.assertRaises(Abstain):schedule.capture(self.target,changed)

    def test_prospective_context_rate_model_needs_variation_and_unseen_target(self):
        rows=cohort(85);now=rows[70][0]['fixture_start_utc']-1800
        with patch('time.time',return_value=now):
            base=nba_dynamic.fit(rows,cutoff_utc=now);contexts=[]
            for r in base['payload']['training'][:45]:
                t=dict(fixture_id=r['fixture_id'],fixture_start_utc=r['start'],home_team_id=r['home'],away_team_id=r['away'],season=base['payload']['season'])
                v=dict(start_gap_hours=24.,back_to_back_calendar_days=True,venue_geodesic_km=None)
                p=dict(format='PROSPECTIVE_NBA_SCHEDULE_CONTEXT_V1',target=t,
                    observed_at_utc=r['start']-1800,source_available_max_utc=r['start']-1801,
                    values=dict(home=deepcopy(v),away=deepcopy(v)))
                contexts.append(dict(payload=p,sha256=digest(p)))
            with self.assertRaisesRegex(Abstain,'VARIATION'):schedule.fit(base,contexts)
            for i,w in enumerate(contexts):
                w['payload']['values']['home']['start_gap_hours']=24+24*(i%3)
                w['sha256']=digest(w['payload'])
            model=schedule.fit(base,contexts);self.assertTrue(model['payload']['calendar_gap_fitted'])
            self.assertFalse(model['payload']['venue_distance_proxy_fitted'])
            target=metadata(rows[71][0]);f=nba_dynamic.predict(base,target,cutoff_utc=now)
            p=dict(contexts[0]['payload'],target=target,observed_at_utc=now,source_available_max_utc=now)
            c=dict(payload=p,sha256=digest(p));new=schedule.predict(base,model,f,c)
            self.assertEqual(new.samples.shape,(10000,4,2));self.assertFalse(new.metadata['actual_itinerary_fitted'])
            bad=deepcopy(c);bad['payload']['target']['fixture_id']=model['payload']['training_ids'][0];bad['sha256']=digest(bad['payload'])
            with self.assertRaisesRegex(Abstain,'FUTURE_PREMATCH'):schedule.predict(base,model,f,bad)
