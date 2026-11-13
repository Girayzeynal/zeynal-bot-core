"""Synthetic settlement/calibration mechanics; never bookmaker or prediction-success evidence."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
from unittest import TestCase,IsolatedAsyncioTestCase
from unittest.mock import AsyncMock,patch

import numpy as np

from core.team_identity import digest
from hybrid_engine.calibration_guard import CalibrationPlan,eligible_records,review_checkpoints,shadow_walk_forward,drift_monitor
from hybrid_engine.decision_layer import DecisionDistribution,QuoteEvidence,RuleEvidence,evaluate_quote,settled_value
from hybrid_engine.decision_integration import DecisionJournal,DecisionService,DecisionReports,render_decision,read_audit_report
from hybrid_engine.decision_metrics import audit_markets
from hybrid_engine.decision_audit import independent_snapshots,native_final,read_snapshots,score_audit,FinalArchive,NativeAssets,replay_snapshot,quotes_from_assets
from hybrid_engine.distributions import Forecast
from hybrid_engine.observed_markets import decimal_price
from hybrid_engine.elite_render import units
from tests.test_release_integration import live_payload
from tests.test_season_archive_audit import NOW,nba


def distribution():
    paths=np.empty((10000,4,2),dtype=np.int32);paths[:5000]=[25,24];paths[5000:8000]=[25,25];paths[8000:]=[24,26]
    f=Forecast('SYNTHETIC',paths.mean(axis=0),samples=paths,metadata={'method':'SYNTHETIC','seed':13})
    trace=dict(league='NBA',season='2026/2027',fixture_id='f',home_team_id='1',away_team_id='2',tipoff_utc=NOW+3600,
        model_version='SYNTHETIC_V1',model_digest='synthetic',prediction_utc=NOW,inputs_available_max_utc=NOW-2)
    return DecisionDistribution(f,trace)


def capture(document,url):
    return dict(provider='SYNTHETIC_TEST_NOT_REAL_FEED',source_url=url,status='DOCUMENT_RECEIVED',http_status=200,
        observed_at_utc=NOW-2,ingested_at_utc=NOW-1,document=document,document_sha256=digest(document))


def quote_and_rule(*,market='TOTAL',period='FULL',line=198.,prices=None,ot=False):
    q=dict(format='EXPLICIT_BOOK_MARKET_V1',league='NBA',season='2026/2027',fixture_id='f',home_team_id='1',away_team_id='2',
        tipoff_utc=NOW+3600,bookmaker_id='SYNTHETIC_ONLY',period=period,market=market,line=line,
        prices={'over':2.,'under':2.} if prices is None else prices)
    rule=dict(format='EXPLICIT_BOOK_SETTLEMENT_V1',bookmaker_id='SYNTHETIC_ONLY',period=period,market=market,
        league='NBA',effective_from_utc=NOW-100,effective_until_utc=None,
        include_overtime=ot,stake_rule='WHOLE_STAKE_WIN_LOSS_PUSH',tie_policy='PUSH')
    qr=capture(q,'https://synthetic.example.test/quotes');rr=capture(rule,'https://synthetic.example.test/rules')
    return (QuoteEvidence.admit_feed(qr,expected_url=qr['source_url'],trusted_document_sha256=qr['document_sha256']),
        RuleEvidence.admit(rr,expected_url=rr['source_url'],trusted_document_sha256=rr['document_sha256']))


class DecisionMathTests(TestCase):
    def setUp(self):
        p=patch('time.time',return_value=NOW);p.start();self.addCleanup(p.stop);self.d=distribution()

    def test_missing_market_never_invents_a_line_or_pick(self):
        r=evaluate_quote(self.d,asof_utc=NOW);self.assertEqual(r['status'],'NO_MARKET_DATA');self.assertIsNone(r['expected_value'])
        self.assertFalse(r['selected']);self.assertIsNone(r['recommended_direction'])

    def test_two_sided_no_vig_and_zero_ev_are_not_forced_picks(self):
        q,r=quote_and_rule();v=evaluate_quote(self.d,q,r,asof_utc=NOW)
        self.assertEqual(v['raw_probabilities'],dict(under=.5,push=0.,over=.5));self.assertEqual(v['status'],'NO_EDGE')
        self.assertEqual(v['expected_value'],dict(over=0.,under=0.));self.assertEqual(v['price_benchmarks']['no_vig']['over_or_home'],.5)

    def test_push_correct_ev_and_conditional_break_even(self):
        q,r=quote_and_rule(line=200.,prices={'under':1.5,'over':2.})
        v=evaluate_quote(self.d,q,r,asof_utc=NOW)
        self.assertEqual(v['raw_probabilities'],dict(under=.5,push=.5,over=0.));self.assertEqual(v['expected_value']['under'],.25)
        self.assertAlmostEqual(v['break_even_unconditional_win_probability']['under'],1/3)
        self.assertEqual(v['status'],'UNCALIBRATED');self.assertFalse(v['selected']);self.assertIsNone(v['confidence_index'])

    def test_american_odds_and_vig_are_not_true_event_probabilities(self):
        price=decimal_price('-110');q,r=quote_and_rule(prices={'over':price,'under':price})
        v=evaluate_quote(self.d,q,r,asof_utc=NOW);self.assertAlmostEqual(v['price_benchmarks']['no_vig']['overround'],.047619047619)
        self.assertLess(v['expected_value']['over'],0);self.assertTrue(v['price_benchmarks']['not_true_event_probabilities'])

    def test_one_sided_quote_has_no_fabricated_no_vig(self):
        q,r=quote_and_rule(prices={'over':2.1});v=evaluate_quote(self.d,q,r,asof_utc=NOW)
        self.assertIsNone(v['price_benchmarks']['no_vig']);self.assertEqual(set(v['expected_value']),{'over'})

    def test_line_without_price_is_explicitly_insufficient(self):
        q,r=quote_and_rule(prices={});v=evaluate_quote(self.d,q,r,asof_utc=NOW)
        self.assertEqual(v['status'],'INSUFFICIENT_DATA');self.assertIn('NO_OBSERVED_PRICES',v['reasons'])

    def test_settlement_rule_is_not_inferred_from_nba_or_close_field(self):
        q,_=quote_and_rule();v=evaluate_quote(self.d,q,asof_utc=NOW)
        self.assertEqual(v['status'],'INSUFFICIENT_DATA');self.assertIsNone(v['raw_probabilities']);self.assertIsNone(v['expected_value'])
        self.assertFalse(q.payload['closing_time_verified'])

    def test_overtime_market_requires_actual_overtime_paths(self):
        q,r=quote_and_rule(ot=True);v=evaluate_quote(self.d,q,r,asof_utc=NOW)
        self.assertEqual(v['status'],'INSUFFICIENT_DATA');self.assertIn('NO_VERIFIED_OVERTIME_SIMULATION_PATHS',v['reasons'])

    def test_settlement_cannot_cross_leagues_or_validity_boundaries(self):
        q,r=quote_and_rule()
        for change in (dict(league='EUROLEAGUE'),dict(effective_from_utc=NOW+1),dict(effective_until_utc=NOW)):
            with self.subTest(change=change):
                payload=dict(r.payload,**change);other=RuleEvidence(payload,digest(payload))
                v=evaluate_quote(self.d,q,other,asof_utc=NOW)
                self.assertEqual(v['status'],'INSUFFICIENT_DATA');self.assertIsNone(v['expected_value'])
                self.assertIn('SETTLEMENT_SCOPE_OR_CLOCK_CONFLICT',v['reasons'])
        for change in (dict(effective_from_utc=True),dict(effective_until_utc=NOW-101),dict(league='')):
            with self.subTest(invalid=change),self.assertRaises(ValueError):RuleEvidence.validate(dict(r.payload,**change))

    def test_real_path_scope_and_overtime_coherence(self):
        ot=np.zeros((10000,2),dtype=np.int32);ot[5000:8000]=[6,4]
        d=DecisionDistribution(self.d.forecast,self.d.trace,overtime_paths=ot)
        q,r=quote_and_rule(market='WINNER',line=0.,ot=True);v=evaluate_quote(d,q,r,asof_utc=NOW)
        self.assertEqual(v['raw_probabilities'],dict(under=.2,push=0.,over=.8))
        ot[0]=[1,1]
        with self.assertRaisesRegex(ValueError,'COHERENT'):DecisionDistribution(self.d.forecast,self.d.trace,overtime_paths=ot)

    def test_home_handicap_sign_and_push(self):
        q,r=quote_and_rule(market='HOME_HANDICAP',line=-4.);v=evaluate_quote(self.d,q,r,asof_utc=NOW)
        self.assertEqual(v['raw_probabilities'],dict(under=.5,push=.5,over=0.))

    def test_all_quarters_halves_and_team_totals_use_the_same_paths(self):
        for period in ('FULL','1Q','2Q','3Q','4Q','1H','2H'):
            for market in ('TOTAL','HOME','AWAY','HOME_HANDICAP'):
                with self.subTest(period=period,market=market):
                    q,r=quote_and_rule(market=market,period=period,line=50.)
                    result=evaluate_quote(self.d,q,r,asof_utc=NOW);self.assertAlmostEqual(sum(result['raw_probabilities'].values()),1)
        self.assertTrue(np.array_equal(self.d.values('1H','TOTAL')+self.d.values('2H','TOTAL'),self.d.values('FULL','TOTAL')))

    def test_mean_median_and_discrete_modes_are_distinguished(self):
        d=self.d.describe('FULL','HOME');self.assertAlmostEqual(d['mean'],99.2);self.assertEqual(d['p50'],100)
        self.assertEqual(d['discrete_modes'],[100]);self.assertFalse(d['coverage_calibrated'])

    def test_quarter_asian_stakes_are_not_silently_treated_as_simple_push_contracts(self):
        q,r=quote_and_rule(line=198.25);v=evaluate_quote(self.d,q,r,asof_utc=NOW)
        self.assertIn('SPLIT_STAKE_ASIAN_QUARTER_LINE_UNSUPPORTED',v['reasons'])

    def test_future_line_and_posthoc_decision_are_different(self):
        q,r=quote_and_rule();p=dict(q.payload,observed_at_utc=NOW+1,ingested_at_utc=NOW+1);future=QuoteEvidence(p,digest(p))
        v=evaluate_quote(self.d,future,r,asof_utc=NOW+10);self.assertIn('QUOTE_NOT_AVAILABLE_AT_FORECAST',v['reasons'])
        v=evaluate_quote(self.d,q,r,asof_utc=NOW+4000);self.assertEqual(v['audit_class'],'POSTHOC_AUDIT_NOT_PREGAME_DECISION')
        self.assertFalse(v['selected'])

    def test_rule_for_other_scope_or_observed_after_forecast_is_refused(self):
        q,r=quote_and_rule();p=dict(r.payload,period='1H');bad=RuleEvidence(p,digest(p))
        self.assertIn('SETTLEMENT_SCOPE_OR_CLOCK_CONFLICT',evaluate_quote(self.d,q,bad,asof_utc=NOW)['reasons'])

    def test_source_identity_mutation_stale_and_invalid_prices_fail_closed(self):
        q,r=quote_and_rule();p=dict(q.payload,fixture_id='other');other=QuoteEvidence(p,digest(p))
        self.assertIn('QUOTE_FIXTURE_SCOPE_CONFLICT',evaluate_quote(self.d,other,r,asof_utc=NOW)['reasons'])
        p=dict(q.payload,observed_at_utc=NOW-301);stale=QuoteEvidence(p,digest(p))
        self.assertIn('STALE_MARKET_QUOTE',evaluate_quote(self.d,stale,r,asof_utc=NOW)['reasons'])
        q.payload['line']=199.
        with self.assertRaisesRegex(ValueError,'MUTATED'):evaluate_quote(self.d,q,r,asof_utc=NOW)
        for price in (1.,float('nan'),True):
            with self.assertRaises(ValueError):quote_and_rule(prices={'over':price})

    def test_shadow_profile_does_not_authorize_a_pick(self):
        q,r=quote_and_rule(line=200.);v=evaluate_quote(self.d,q,r,asof_utc=NOW,calibration={'pretend_approved':True})
        self.assertIsNone(v['recommended_direction']);self.assertIn('SHADOW_CANDIDATE_CANNOT_AUTHORIZE_LIVE_SELECTION',v['reasons'])


def calibration_rows(n):
    base=1700000000;rows=[]
    for i in range(n):
        start=base+i*86400
        rows.append(dict(league='NBA',model_version='SYNTHETIC_V1',period='FULL',market='WINNER',settlement_scope='REGULATION_ONLY',
            fixture_id='fixture-'+str(i),snapshot_sha256='snapshot-'+str(i),probabilities=[.9,.05,.05],outcome=0 if i%10<6 else 2,
            prediction_utc=start-3600,tipoff_utc=start,label_available_utc=start+10800,inputs_available_max_utc=start-7200,
            model_fit_cutoff_utc=base-86400,model_training_ids=[],data_class='SYNTHETIC_TEST'))
    return rows


def predeclared_plan():
    with patch('time.time',return_value=1699800000):return CalibrationPlan.register()


class GuardTests(TestCase):
    def test_registered_plan_is_reused_and_not_refitted_on_refresh(self):
        from hybrid_engine.calibration_guard import read_or_register_plan
        with TemporaryDirectory() as tmp:
            a=read_or_register_plan(tmp)
            with patch('time.time',return_value=int(time.time())+20):b=read_or_register_plan(tmp)
            self.assertEqual(a,b);self.assertEqual(len(list(Path(tmp).glob('plan-*.json'))),1)

    def test_calibration_implementation_change_invalidates_the_old_plan(self):
        p=predeclared_plan()
        with patch('hybrid_engine.calibration_guard.Path.read_bytes',return_value=b'changed'):
            with self.assertRaisesRegex(ValueError,'IMPLEMENTATION_CHANGED'):p.validate()

    def test_100_250_500_are_review_checkpoints_not_fit_triggers(self):
        for n,reached,next_n in [(99,[],100),(100,[100],250),(250,[100,250],500),(500,[100,250,500],None)]:
            r=review_checkpoints(calibration_rows(n),asof_utc=int(time.time()),plan=predeclared_plan())['groups'][0]
            self.assertEqual(r['reached_review_checkpoints'],reached);self.assertEqual(r['next_checkpoint'],next_n)
            self.assertFalse(r['automatic_refit']);self.assertFalse(r['automatic_promotion'])

    def test_snapshot_variants_cannot_inflate_independent_forecast_counts(self):
        rows=calibration_rows(4);versions=[dict(r,snapshot_sha256=r['snapshot_sha256']+'-later',prediction_utc=r['prediction_utc']+1) for r in rows]
        self.assertEqual(len(eligible_records(rows+versions,asof_utc=int(time.time()))),4)

    def test_one_match_never_fits_or_calibrates(self):
        r=shadow_walk_forward(calibration_rows(1),predeclared_plan(),asof_utc=int(time.time()))
        self.assertEqual(r['groups'][0]['evaluated_count'],0);self.assertFalse(r['automatic_model_update'])

    def test_plan_cannot_be_backdated_or_thresholds_lowered(self):
        with self.assertRaises(ValueError):CalibrationPlan.register(registered_at_utc=int(time.time())-100)
        plan=predeclared_plan();p=dict(plan.payload,minimum_past_fit=1)
        with self.assertRaisesRegex(ValueError,'POLICY_MUTATED'):CalibrationPlan(p,digest(p)).validate()

    def test_plan_written_after_predictions_is_not_confirmatory(self):
        r=shadow_walk_forward(calibration_rows(200),CalibrationPlan.register(),asof_utc=int(time.time()))
        self.assertEqual(r['groups'][0]['post_plan_target_count'],0);self.assertFalse(r['explicit_approval_present'])

    def test_shadow_time_order_reproducibility_uncertainty_and_no_promotion(self):
        rows=calibration_rows(300);a=shadow_walk_forward(rows,predeclared_plan(),asof_utc=int(time.time()))
        b=shadow_walk_forward(rows,predeclared_plan(),asof_utc=int(time.time()))
        self.assertEqual(a,b);g=a['groups'][0];self.assertGreaterEqual(g['evaluated_count'],100)
        self.assertIsNotNone(g['uncertainty']['interval']);self.assertFalse(g['real_data_only'])
        self.assertGreaterEqual(g['uncertainty']['expected_bootstrap_samples_per_corrected_tail'],10)
        self.assertFalse(g['eligible_for_explicit_user_review']);self.assertIn('NO_GO',a['deployment_decision'])
        for r in g['evaluations']:
            self.assertLess(r['fit_available_max_utc'],r['prediction_utc']);self.assertNotIn(r['fixture_id'],r['fit_ids'])

    def test_changing_future_outcomes_cannot_change_earlier_shadow_predictions(self):
        rows=calibration_rows(200);p=predeclared_plan();a=shadow_walk_forward(rows,p,asof_utc=int(time.time()))
        changed=deepcopy(rows)
        for r in changed[175:]:r['outcome']=1
        b=shadow_walk_forward(changed,p,asof_utc=int(time.time()))
        aa=[r['candidate'] for r in a['groups'][0]['evaluations'] if r['fixture_id'] not in {r['fixture_id'] for r in rows[175:]}]
        bb=[r['candidate'] for r in b['groups'][0]['evaluations'] if r['fixture_id'] not in {r['fixture_id'] for r in rows[175:]}]
        self.assertEqual(aa,bb)

    def test_future_data_target_training_and_conflicting_final_are_rejected(self):
        rows=calibration_rows(2)
        for key,value in [('inputs_available_max_utc',rows[0]['prediction_utc']+1),('model_training_ids',[rows[0]['fixture_id']])]:
            bad=deepcopy(rows);bad[0][key]=value
            with self.assertRaisesRegex(ValueError,'STRICT_PREMATCH'):eligible_records(bad,asof_utc=int(time.time()))
        with self.assertRaisesRegex(ValueError,'CONFLICTING'):eligible_records(rows+[dict(rows[0],outcome=1)],asof_utc=int(time.time()))

    def test_drift_is_observation_only_and_requires_disjoint_prior_reference(self):
        self.assertEqual(drift_monitor(calibration_rows(4),asof_utc=int(time.time()))['status'],'INSUFFICIENT_DATA')
        rows=calibration_rows(100);r=drift_monitor(rows,asof_utc=int(time.time()))
        self.assertEqual(r['status'],'NO_VERIFIED_PRIOR_REFERENCE');self.assertFalse(r['model_update'])


class AuditJournalTests(TestCase):
    def setUp(self):
        p=patch('time.time',return_value=NOW);p.start();self.addCleanup(p.stop)

    def test_decisions_are_immutable_and_all_lines_are_recorded_once(self):
        with TemporaryDirectory() as tmp:
            j=DecisionJournal(Path(tmp)/'decisions.sqlite');q,r=quote_and_rule();q2,r2=quote_and_rule(line=200.)
            a=j.record(snapshot_sha256='s',distribution=distribution(),quotes=[q,q2],rule_by_quote={q.sha256:r,q2.sha256:r2})
            b=j.record(snapshot_sha256='s',distribution=distribution(),quotes=[q2,q],rule_by_quote={q.sha256:r,q2.sha256:r2})
            self.assertEqual(a,b);self.assertEqual(len(j.read()),1);self.assertEqual(len(a['all_quote_ids']),2)
            self.assertFalse(any(e['selected'] for e in a['evaluations']))
            with sqlite3.connect(j.journal.path) as db:
                with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM delivery_events')
            self.assertTrue(all(units(p)<=3200 for p in render_decision(a)))

    def test_decision_journal_never_uses_production_storage(self):
        with self.assertRaises(ValueError):DecisionJournal('/data/no.sqlite')

    def test_market_metric_manifest_cannot_drop_unselected_lines(self):
        q,r=quote_and_rule();d=distribution();e=evaluate_quote(d,q,r,asof_utc=NOW)
        p=live_payload();p.update(fixture_id='f',prediction_generated_at_utc=NOW);p['home']['provider_id']='1';p['away']['provider_id']='2'
        records=[dict(snapshot=p,snapshot_sha256='s')]
        batch=dict(snapshot_sha256='s',all_quote_ids=[q.sha256,'missing-unselected'],evaluations=[e],recorded_at_utc=NOW)
        with self.assertRaisesRegex(ValueError,'CHERRY_PICKED'):audit_markets(records,[batch],{})

    def test_market_push_settlement_scope_and_unselected_metrics(self):
        q,r=quote_and_rule(line=200.);d=distribution();e=evaluate_quote(d,q,r,asof_utc=NOW)
        p=live_payload();p.update(fixture_id='f',prediction_generated_at_utc=NOW);p['home']['provider_id']='1';p['away']['provider_id']='2'
        batch=dict(snapshot_sha256='s',all_quote_ids=[q.sha256],evaluations=[e],recorded_at_utc=NOW)
        report=audit_markets([dict(snapshot=p,snapshot_sha256='s')],[batch],{'f':dict(periods={'home':[25]*4,'away':[25]*4})})
        g=report['groups'][0];self.assertEqual(g['metrics']['push_rate'],1);self.assertEqual(g['metrics']['unselected_count'],1)
        self.assertEqual(g['metrics']['selected_count'],0);self.assertIsNone(g['metrics']['direction_hit_rate'])

    def test_posthoc_decisions_are_not_pregame_market_success(self):
        q,r=quote_and_rule();e=evaluate_quote(distribution(),q,r,asof_utc=NOW+4000)
        p=live_payload();p.update(fixture_id='f',prediction_generated_at_utc=NOW)
        batch=dict(snapshot_sha256='s',all_quote_ids=[q.sha256],evaluations=[e],recorded_at_utc=NOW+4000)
        report=audit_markets([dict(snapshot=p,snapshot_sha256='s')],[batch],{})
        self.assertEqual(report['groups'],[]);self.assertEqual(report['excluded']['POSTHOC_DECISION_NOT_PREGAME_EVIDENCE'],1)

    def test_two_overtimes_are_not_regulation_score_or_period_error(self):
        periods=dict(home=[25]*4+[11,8],away=[25]*4+[11,12])
        self.assertEqual(settled_value(periods,'FULL','TOTAL'),200);self.assertEqual(settled_value(periods,'FULL','TOTAL',include_overtime=True),242)
        self.assertEqual(settled_value(periods,'FULL','WINNER'),0);self.assertEqual(settled_value(periods,'FULL','WINNER',include_overtime=True),-4)
        self.assertEqual(settled_value(periods,'2H','TOTAL'),100);self.assertEqual(settled_value(periods,'2H','TOTAL',include_overtime=True),142)

    def test_first_snapshot_dedupe_never_selects_a_later_better_forecast(self):
        p=live_payload();p.update(created_at_utc=NOW,prediction_generated_at_utc=NOW)
        later=deepcopy(p);later['created_at_utc']=NOW+1;later['model_digest']='later'
        rows,meta=independent_snapshots([dict(snapshot=later,snapshot_sha256='b'),dict(snapshot=p,snapshot_sha256='a')])
        self.assertEqual(rows[0]['snapshot_sha256'],'a');self.assertEqual(meta['duplicates_not_independent'],1)


class DecisionIntegrationTests(IsolatedAsyncioTestCase):
    async def test_abstention_is_not_replaced_with_a_pick(self):
        base=SimpleNamespace(analyze=AsyncMock(return_value=dict(status='ABSTAIN',html='source missing')))
        wrapped=DecisionService(base,None,None);self.assertEqual(await wrapped.analyze('NBA'),dict(status='ABSTAIN',html='source missing'))


ROOT=Path(__file__).resolve().parents[1]


class NativeAuditRegressionTests(TestCase):
    @classmethod
    def setUpClass(cls):
        from hybrid_engine.frozen_archive import read_gzip
        cls.records=read_snapshots(ROOT/'docs/prospective/nba-20261113');cls.selected,_=independent_snapshots(cls.records)
        cls.sources=read_gzip(ROOT/'docs/evidence/phase844-native-nba-finals-20261113.json.gz')
        cls.outcomes={r['snapshot']['fixture_id']:native_final(cls.sources[r['snapshot']['provider_fixture_ids'][0]],r['snapshot']) for r in cls.selected}

    def test_actual_two_overtime_result_is_scored_as_regulation_tie(self):
        before=digest(self.records);report=score_audit(self.records,self.outcomes)
        self.assertEqual(report['settled_independent_forecasts'],4);self.assertEqual(report['deduplication']['input_snapshots'],8)
        self.assertEqual(report['groups'][0]['metrics']['winner_direction']['correct'],3)
        washington=next(x for x in report['per_fixture'] if x['provider_fixture_ids']==['401909977'])
        self.assertEqual(washington['regulation'],[121,121]);self.assertEqual(washington['final_with_ot'],[140,144]);self.assertEqual(washington['overtime_periods'],2)
        self.assertEqual(before,digest(self.records));self.assertFalse(report['automatic_calibration'])

    def test_verified_coverage_counts_are_four_not_eight(self):
        report=score_audit(self.records,self.outcomes);coverage=report['groups'][0]['interval_coverage']['markets']['TOTAL']
        self.assertEqual(coverage['P25_P75']['n'],4);self.assertEqual(coverage['P25_P75']['hits'],2)
        self.assertEqual(coverage['P05_P95']['hits'],4);self.assertLess(coverage['P05_P95']['wilson_95'][0],.6)

    def test_final_is_bound_to_native_fixture_source_and_period_totals(self):
        p=self.selected[0]['snapshot'];source=deepcopy(self.sources[p['provider_fixture_ids'][0]])
        source['source_url']='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=wrong'
        with self.assertRaisesRegex(ValueError,'SOURCE_BINDING'):native_final(source,p)
        source=deepcopy(self.sources[p['provider_fixture_ids'][0]])
        source['document']['header']['competitions'][0]['competitors'][0]['linescores'][0]['displayValue']='999'
        source['document_sha256']=digest(source['document'])
        with self.assertRaises(ValueError):native_final(source,p)

    def test_currently_nonfinal_status_cannot_be_accepted_as_final(self):
        p=self.selected[0]['snapshot'];source=deepcopy(self.sources[p['provider_fixture_ids'][0]])
        source['document']['header']['competitions'][0]['status']['type'].update(completed=False,state='in',name='STATUS_IN_PROGRESS')
        source['document_sha256']=digest(source['document']);self.assertIsNone(native_final(source,p))

    def test_result_archive_is_append_only_idempotent_and_rechecks_native_hash(self):
        p=self.selected[0]['snapshot'];source=self.sources[p['provider_fixture_ids'][0]]
        with TemporaryDirectory() as tmp:
            archive=FinalArchive(tmp);archive.ingest(source,p);archive.ingest(source,p)
            self.assertEqual(len(list(Path(tmp).glob('result-*.json'))),1);self.assertEqual(len(archive.read([p])),1)
            result=json.loads(next(Path(tmp).glob('result-*.json')).read_text());native=Path(tmp)/result['payload']['source_file']
            content=json.loads(native.read_text());content['observed_at_utc']-=1;native.write_text(json.dumps(content))
            with self.assertRaisesRegex(ValueError,'SOURCE_FILE_PIN'):archive.read([p])

    def test_first_issued_frozen_sampler_replay_still_matches_original_samples(self):
        assets=NativeAssets(ROOT/'docs/evidence/nba-phase843-prospective-native-20261113.tar.gz')
        try:
            r=self.selected[0];d,training=replay_snapshot(r,assets);quotes,rejected=quotes_from_assets(r,assets)
            self.assertNotIn(r['snapshot']['fixture_id'],training);self.assertEqual(len(d.paths),10000)
            self.assertTrue(quotes)
            for q in quotes:
                e=evaluate_quote(d,q,asof_utc=int(time.time()))
                self.assertEqual(e['status'],'INSUFFICIENT_DATA');self.assertIsNone(e['expected_value'])
                self.assertFalse(e['selected']);self.assertIn('SETTLEMENT_RULE_UNVERIFIED',e['reasons'])
        finally:assets.close()

    def test_real_outcome_report_can_be_pinned_for_test_bot_accuracy_and_compare(self):
        report=score_audit(self.records,self.outcomes)
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'report.json';w=dict(payload=report,sha256=digest(report));path.write_text(json.dumps(w))
            verified=read_audit_report(path,w['sha256']);base=SimpleNamespace(read=lambda *args:{})
            journal=DecisionJournal(Path(tmp)/'decisions.sqlite');reports=DecisionReports(base,journal,audit_report=verified)
            text=reports.render_accuracy(reports.read('NBA'));self.assertIn('n=4',text);self.assertIn('kalibrasyon doğrulanmadı',text)
            comparison=reports.render_compare(reports.read('NBA','401909977'));self.assertIn('[121, 121]',comparison);self.assertIn('[140, 144]',comparison)
            base.render_accuracy=lambda report:'SYNTHETIC_EL_REPORT_PRESERVED'
            self.assertIn('SYNTHETIC_EL_REPORT_PRESERVED',reports.render_accuracy(reports.read('EUROLEAGUE')))
            report['automatic_calibration']=True;path.write_text(json.dumps(dict(payload=report,sha256=digest(report))))
            with self.assertRaisesRegex(ValueError,'OBSERVATION_ONLY'):read_audit_report(path,digest(report))
