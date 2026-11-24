"""Real models/registries/handlers with synthetic sources, rules and Bot API only."""
import asyncio
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase,IsolatedAsyncioTestCase
from unittest.mock import AsyncMock,Mock,patch

import numpy as np
from core.team_identity import digest
from hybrid_engine import nba_dynamic
from hybrid_engine.current_assessment import CurrentAssessments,install_display
from hybrid_engine.data import Abstain
from hybrid_engine.native_fixture_recheck import NativeFixtureRecheck
from hybrid_engine.research_diagnostics import ResearchCycle
from hybrid_engine.settlement_rules import RuleBook,evaluate_bound
from tests import test_current_market_review as market
from tests import test_native_fixture_recheck as native


class AssessmentTests(TestCase):
    def setUp(self):
        self.h=native.SyntheticCalendarGuardsTests('runTest');self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.target,self.receipt=self.h.fixture()
        from tests.test_adaptive_research import cohort
        rows=cohort(85);delta=self.target['fixture_start_utc']-rows[71][0]['fixture_start_utc']
        for vs in rows:
            r=vs[0];r['season']=self.target['season'];r['box']['season']=self.target['season']
            for obj in (r,r['box'],r['box']['source']):
                for key in ('fixture_start_utc','observed_at_utc','ingested_at_utc'):
                    if key in obj:obj[key]+=delta
        self.model=nba_dynamic.fit(rows,cutoff_utc=self.h.now)
        self.rows=rows
        t=self.target
        self.original=dict(league='NBA',season=t['season'],fixture_id=t['fixture_id'],
            fixture_start_utc=t['fixture_start_utc'],model_digest='a'*64,
            home=dict(provider_id=t['home_team_id']),away=dict(provider_id=t['away_team_id']),
            parameter_fit_cutoff_utc=self.h.now-10*86400)
        self.case=dict(target=t,original=digest(self.original),snapshot=self.original,code='NBA')
        self.fetch=Mock(side_effect=lambda *args:dict(deepcopy(self.receipt),observed_at_utc=self.h.now-1,ingested_at_utc=self.h.now))
        self.worker=SimpleNamespace(verify=NativeFixtureRecheck(self.fetch).verify,
            cases=lambda:[self.case],labels=lambda:[])
        self.study=SimpleNamespace(fit=lambda season:(self.model,False))
        self.assess=CurrentAssessments(self.root/'current',self.worker,self.study)
        self.plan=self.assess.plan(create=True)

    def capture(self):return self.assess._capture(self.case,self.model,self.plan)

    def files(self):return {str(f.relative_to(self.root)):f.read_bytes() for f in self.root.rglob('*') if f.is_file()}

    def test_joint_paths_replay_exactly_without_model_fit_or_inference_in_market_view(self):
        p,new=self.capture();self.assertTrue(new)
        before=self.files()
        with patch('hybrid_engine.nba_dynamic.predict',side_effect=AssertionError('NO_NEW_INFERENCE')):
            snap,distribution=self.assess.market_context(self.original)
            text=self.assess.render(self.original)
        self.assertEqual(distribution.paths.shape,(10000,4,2))
        self.assertEqual(snap['linked_original_snapshot_sha256'],digest(self.original))
        self.assertEqual(snap['intervals']['sample_sha256'],p['intervals']['sample_sha256'])
        self.assertIn('GÜNCEL',text);self.assertIn('oyuncu, haber ve seyahat etkisi uygulanmadı',text)
        self.assertEqual(before,self.files());self.assertFalse(p['eligible_for_original_forecast_metrics'])

    def test_retry_and_hourly_refresh_preserve_first_record_and_original(self):
        p,new=self.capture();before=self.files();self.h.now+=1
        q,new=self.capture();self.assertFalse(new);self.assertEqual(p,q);self.assertEqual(before,self.files())
        self.h.now+=3600
        newer,new=self.capture();self.assertTrue(new)
        self.assertEqual(len(self.assess.registry.records()),2)
        self.assertEqual(p['original_snapshot_sha256'],newer['original_snapshot_sha256'])
        for name,raw in before.items():self.assertEqual((self.root/name).read_bytes(),raw)

    def test_stale_model_and_five_minute_window_cannot_publish(self):
        old=deepcopy(self.model);old['payload']['cutoff_utc']=self.h.now-86401;old['sha256']=digest(old['payload'])
        with self.assertRaisesRegex(Abstain,'MODEL_TOO_OLD'):self.assess._capture(self.case,old,self.plan)
        self.h.now=self.target['fixture_start_utc']-300
        with self.assertRaises(Abstain):self.capture()
        self.assertEqual(self.assess.registry.records(),[])

    def test_changed_original_or_samples_are_not_silently_replaced(self):
        p,_=self.capture()
        with self.assertRaisesRegex(Abstain,'ORIGINAL_CONFLICT'):
            self.assess._capture(dict(self.case,original='f'*64),self.model,self.plan)
        changed=dict(self.original,model_digest='b'*64)
        with self.assertRaisesRegex(ValueError,'ORIGINAL_PIN'):self.assess.market_context(changed)
        ref=next(r for r in p['assets'] if r['file'].startswith('joint-paths-'))
        f=self.assess.registry.root/ref['file'];obj=json.loads(f.read_text());obj['samples'][0][0][0]+=1
        f.write_text(json.dumps(obj))
        with self.assertRaisesRegex(ValueError,'ASSET_PIN'):self.assess.market_context(self.original)

    def test_expired_or_started_assessment_is_archived_not_current_market_input(self):
        self.capture();self.h.now+=3601
        with self.assertRaisesRegex(Abstain,'STALE_OR_STARTED'):self.assess.market_context(self.original)
        self.assertIn('ARŞİV',self.assess.render(self.original))
        self.assertIsNone(self.assess.available_market_context(self.original))

    def test_first_assessment_only_in_own_metrics_not_updates_or_wrong_original(self):
        p,_=self.capture();self.h.now+=3600;self.capture()
        t=self.target;self.h.now=t['fixture_start_utc']+7200
        label=dict(fixture_id=t['fixture_id'],snapshot_sha256=digest(self.original),model_digest='a'*64,
            actual=[100,100],actual_periods=dict(home=[25,25,25,25,7],away=[25,25,25,25,4]),
            fixture_start_utc=t['fixture_start_utc'],label_available_utc=self.h.now)
        result=self.assess.performance([label]);m=result['groups'][0]['metrics']
        self.assertEqual(m['n'],1);self.assertAlmostEqual(m['total']['mae'],abs(p['candidate']['total']-200))
        self.assertFalse(result['original_metrics_changed']);self.assertFalse(result['superiority_claim'])
        self.assertEqual(self.assess.performance([dict(label,snapshot_sha256='b'*64)])['groups'],[])

    def test_native_paired_first_forecast_vs_first_current_candidate_without_retrofit(self):
        p,_=self.capture()
        self.h.now=self.target['fixture_start_utc']+7200
        published=p['prediction_generated_at_utc']-60
        original=[p['candidate']['home']+10.,p['candidate']['away']+10.]
        label=dict(fixture_id=self.target['fixture_id'],snapshot_sha256=digest(self.original),
            model_digest='a'*64,season=self.target['season'],actual=[100,100],
            actual_periods=dict(home=[25,25,25,25],away=[25,25,25,25]),
            fixture_start_utc=self.target['fixture_start_utc'],label_available_utc=self.h.now,
            prediction=list(original),prediction_generated_at_utc=published-10,
            first_archived_at_utc=published)
        output=self.assess.performance([label]);group=output['groups'][0]
        pair=group['paired']
        self.assertEqual(group['paired_n'],1)
        self.assertEqual(pair['status'],'PAIRED_DESCRIPTIVE_ONLY')
        self.assertAlmostEqual(pair['first_forecast_total_mae'],abs(sum(original)-200))
        self.assertAlmostEqual(pair['candidate_total_mae'],abs(p['candidate']['total']-200))
        self.assertAlmostEqual(pair['total_mae_delta'],
            abs(sum(original)-200)-abs(p['candidate']['total']-200))
        self.assertFalse(output['original_metrics_changed'])
        self.assertFalse(output['automatic_promotion'])
        self.assess.last_report=dict(performance=output)
        display=self.assess.render_performance()
        self.assertIn('İlk toplam MAE',display)
        self.assertIn('Güncel aday toplam MAE',display)
        self.assertIn('54 maça sonradan tahmin yazılmaz',display)

    def test_missing_or_late_original_publication_never_becomes_paired_evidence(self):
        p,_=self.capture()
        self.h.now=self.target['fixture_start_utc']+7200
        original=dict(fixture_id=self.target['fixture_id'],
            snapshot_sha256=digest(self.original),model_digest='a'*64,
            actual=[100,100],actual_periods=dict(home=[25,25,25,25],away=[25,25,25,25]),
            fixture_start_utc=self.target['fixture_start_utc'],label_available_utc=self.h.now,
            prediction=[105,105],prediction_generated_at_utc=p['prediction_generated_at_utc']-100,
            first_archived_at_utc=p['prediction_generated_at_utc']+1)
        late=self.assess.performance([original])['groups'][0]
        self.assertEqual(late['metrics']['n'],1)
        self.assertEqual(late['paired_n'],0)
        self.assertEqual(late['paired']['status'],'NO_VERIFIED_FIRST_FORECAST_PAIR')
        missing=dict(original);missing.pop('first_archived_at_utc')
        self.assertEqual(self.assess.performance([missing])['groups'][0]['paired_n'],0)

    def test_empty_research_cycle_is_not_reported_as_published_score(self):
        self.worker.cases=lambda:[]
        report=self.assess.tick()
        self.assertEqual(report['status'],'CHECKED_NO_NEW_CANDIDATE')
        self.assertEqual(report['candidate_published_count'],0)
        self.assertEqual(report['capture_attempt_count'],0)
        self.assertEqual(report['captures'],[])
        self.assertEqual(len(self.assess.registry.records()),0)

    def test_requested_fixture_exposes_exact_eligibility_blocker(self):
        self.worker.cases=lambda:[]
        report=self.assess.tick(preferred_fixture_id='expected-nba-fixture')
        self.assertEqual(report['status'],'PARTIAL_ABSTAIN')
        self.assertEqual(report['requested_fixture_status'],'NOT_ELIGIBLE')
        self.assertEqual(report['candidate_published_count'],0)
        self.assertEqual(report['captures'][0]['reason'],'CURRENT_REQUESTED_FIXTURE_NOT_ELIGIBLE')

    def test_tick_archives_candidate_without_hundred_match_calibration_gate(self):
        report=self.assess.tick();self.assertEqual(report['captures'][0]['status'],'ARCHIVED')
        self.assertEqual(len(self.assess.registry.records()),1)

    def test_concurrent_commands_cannot_create_two_records_for_same_hour(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(self.capture) for _ in range(2)]
            result=[]
            for f in futures:
                try:result.append(f.result())
                except Abstain as exc:self.assertIn(str(exc),('EUROPE_PREMATCH_PUBLICATION_BUSY','CURRENT_ASSESSMENT_COMMIT_UNCONFIRMED'))
        self.assertEqual(sum(new for _,new in result),1)
        self.assertEqual(len(self.assess.registry.records()),1)
        if len(result)==2:self.assertEqual(result[0][0],result[1][0])

    def test_cutoff_crossed_during_commit_is_retained_but_excluded(self):
        # The actual durable-publication receipt is sampled after the base
        # registry has completed, never inferred from an earlier issue clock.
        from hybrid_engine.adaptive_research import Registry
        original=Registry.record
        def cross(registry,payload):
            p,new=original(registry,payload);self.h.now=self.target['fixture_start_utc']-299
            return p,new
        with patch.object(Registry,'record',cross):
            with self.assertRaisesRegex(Abstain,'LATE_COMMIT_EXCLUDED'):self.capture()
        self.assertEqual(self.assess.registry.records(),[])

    def test_changed_verified_box_inputs_change_stored_score_and_market_distribution(self):
        from hybrid_engine.boxes import checked_stats
        first,_=self.capture();self.h.now+=3600
        rows=deepcopy(self.rows)
        for vs in rows[64:71]:
            for side in ('home','away'):
                b=vs[0]['box']['teams'][side];b['fga2']+=15;b.update(checked_stats(b))
        model=nba_dynamic.fit(rows,cutoff_utc=self.h.now)
        second,new=self.assess._capture(self.case,model,self.plan)
        self.assertTrue(new)
        self.assertNotAlmostEqual(first['candidate']['total'],second['candidate']['total'])
        snap,dist=self.assess.market_context(self.original)
        self.assertEqual(snap['intervals']['sample_sha256'],second['intervals']['sample_sha256'])
        self.assertAlmostEqual(dist.forecast.summary()['total'],second['candidate']['total'])

    def test_foreign_fixture_is_refused_before_new_assessment(self):
        bad=deepcopy(self.case);bad['target']['home_team_id']='999'
        with self.assertRaises(Abstain):self.assess._capture(bad,self.model,self.plan)
        self.assertEqual(self.assess.registry.records(),[])

    def test_both_european_leagues_use_native_fixture_and_real_pace_model_paths(self):
        from tests.test_europe_integration import Source,NOW
        from hybrid_engine.adaptive_data import native_catalog
        from hybrid_engine.adaptive_research import AdaptiveResearch
        from hybrid_engine.europe_models import season_url
        for code,league in [('EUROLEAGUE','EuroLeague'),('EUROCUP','EuroCup')]:
            source=Source(code,lambda:self.h.now)
            for game in source.raw['data']:
                at=datetime.fromisoformat(game['utcDate']);game['utcDate']=datetime.fromtimestamp(int(at.timestamp())+self.h.now-NOW,timezone.utc).isoformat()
            receipt=source('EUROLEAGUE_LIVE',season_url(code,2026))
            g=next(g for g in native_catalog(receipt,code,2026)['payload']['fixtures'] if not g['completed'] and g['home_team_id']=='PRS')
            t=dict(league=league,season='2026/2027',fixture_id=g['canonical_id'],fixture_start_utc=g['start_ts_utc'],
                home_team_id=g['home_team_id'],away_team_id=g['away_team_id'],provider_fixture_ids=g['provider_fixture_ids'])
            original=dict(self.original,league=code,fixture_id=t['fixture_id'],fixture_start_utc=t['fixture_start_utc'],
                home=dict(provider_id=t['home_team_id']),away=dict(provider_id=t['away_team_id']))
            rows=deepcopy(self.rows)
            for vs in rows:
                r=vs[0]
                for obj in (r,r['box']):
                    obj['league']=league
                    for side in ('home','away'):obj[side+'_team_id']='PRS' if obj[side+'_team_id']=='1' else 'ULK'
            v2=AdaptiveResearch(self.root/code/'v2');v2.plan(create=True)
            model,_=v2.fit(rows,league,t['season'])
            worker=SimpleNamespace(verify=NativeFixtureRecheck(source).verify)
            assess=CurrentAssessments(self.root/code/'current',worker,None);plan=assess.plan(create=True)
            p,new=assess._capture(dict(target=t,original=digest(original)),model,plan)
            self.assertTrue(new)
            snap,dist=assess.market_context(original)
            self.assertEqual(dist.paths.shape,(10000,4,2));self.assertEqual(snap['league'],code)
            self.assertEqual(p['features']['players'],'NOT_APPLIED_REQUIRES_VERIFIED_MINUTES_AND_FITTED_PLAYER_MODEL')


class RuleBindingTests(TestCase):
    def setUp(self):
        self.h=market.CurrentReviewTests('runTest');self.h.setUp();self.addCleanup(self.h.doCleanups)

    def book(self,**changes):
        q=dict(self.h.rule(**changes).payload)
        for k in ('observed_at_utc','ingested_at_utc','source_url','source_document_sha256','attestation'):q.pop(k,None)
        receipt=dict(provider='EXPLICIT_STRUCTURED_RULE_INPUT',status='DOCUMENT_RECEIVED',http_status=200,
            source_url='https://rules.synthetic.invalid/only-tests',observed_at_utc=market.NOW-1,
            ingested_at_utc=market.NOW,document=q,document_sha256=digest(q))
        payload=dict(format='CONFIGURED_RULE_RECEIPTS_V1',entries=[dict(receipt=receipt,
            expected_url=receipt['source_url'],document_sha256=receipt['document_sha256'])])
        path=self.h.root/'rules.json';path.write_text(json.dumps(dict(payload=payload,sha256=digest(payload))))
        return RuleBook(path,digest(payload))

    def evaluate(self,book,cutoff=None):
        snap=dict(self.h.snap,parameter_fit_cutoff_utc=market.NOW-60 if cutoff is None else cutoff)
        return evaluate_bound(SimpleNamespace(rule_book=book),self.h.obs,self.h.dist,snap,
            asof_utc=market.NOW,native_quotes=self.h.quotes)

    def test_configured_rule_reaches_real_evaluator_and_enables_raw_contract_math(self):
        result=self.evaluate(self.book());row=result['rows'][0]
        self.assertIsNotNone(row['expected_value']);self.assertIsNone(row['calibrated_probabilities'])
        self.assertFalse(result['selection_enabled'])

    def test_missing_rule_ot_paths_or_old_model_remain_explicit_blocks(self):
        self.assertIsNone(self.evaluate(RuleBook())['rows'][0]['expected_value'])
        self.assertEqual(self.evaluate(self.book(overtime=True))['rows'][0]['status'],'NO_VERIFIED_OVERTIME_SIMULATION_PATHS')
        old=self.evaluate(self.book(),market.NOW-21601)['rows'][0]
        self.assertEqual(old['status'],'MODEL_PARAMETERS_STALE');self.assertIsNone(old['expected_value'])
        from hybrid_engine.market_direction_ui import cards
        view=self.evaluate(self.book(),market.NOW-21601)
        result=cards(view,self.h.dist.forecast,tipoff_utc=self.h.snap['fixture_start_utc'],fixture_id=self.h.snap['fixture_id'])
        self.assertTrue(result);self.assertFalse(any(c['current'] for c in result))

    def test_current_v3_market_uses_24h_ceiling_but_legacy_stays_6h(self):
        from hybrid_engine.market_direction_ui import cards
        from hybrid_engine.time_policy import MAXIMUM_V3_MODEL_AGE_SECONDS
        asof=market.NOW
        context=dict(self.h.snap,record_type='CURRENT_RESEARCH_ASSESSMENT_V1',
                     parameter_fit_cutoff_utc=asof-7*3600)
        current=evaluate_bound(SimpleNamespace(rule_book=self.book()),self.h.obs,self.h.dist,
                               context,asof_utc=asof,native_quotes=self.h.quotes)
        self.assertEqual(current['model_fit_age_limit_seconds'],MAXIMUM_V3_MODEL_AGE_SECONDS)
        self.assertNotEqual(current['rows'][0]['status'],'MODEL_PARAMETERS_STALE')
        shown=cards(current,self.h.dist.forecast,tipoff_utc=self.h.snap['fixture_start_utc'],
                    fixture_id=self.h.snap['fixture_id'])
        self.assertTrue(shown)
        self.assertTrue(any(c['current'] for c in shown))
        legacy=self.evaluate(self.book(),asof-7*3600)
        self.assertEqual(legacy['model_fit_age_limit_seconds'],21600)
        self.assertEqual(legacy['rows'][0]['status'],'MODEL_PARAMETERS_STALE')
        context['parameter_fit_cutoff_utc']=asof-MAXIMUM_V3_MODEL_AGE_SECONDS-1
        expired=evaluate_bound(SimpleNamespace(rule_book=self.book()),self.h.obs,self.h.dist,
                               context,asof_utc=asof,native_quotes=self.h.quotes)
        self.assertEqual(expired['rows'][0]['status'],'MODEL_PARAMETERS_STALE')
        self.assertFalse(any(c['current'] for c in cards(
            expired,self.h.dist.forecast,tipoff_utc=self.h.snap['fixture_start_utc'],
            fixture_id=self.h.snap['fixture_id'])))

    def test_tampered_manifest_and_ambiguous_rules_refused(self):
        book=self.book();w=json.loads(book.path.read_text());w['payload']['entries']*=2
        w['sha256']=digest(w['payload']);book.path.write_text(json.dumps(w))
        with self.assertRaisesRegex(ValueError,'TRUSTED_PIN'):book.rules()
        with self.assertRaisesRegex(ValueError,'AMBIGUOUS_SCOPE'):RuleBook(book.path,w['sha256']).rules()

    def test_configured_rules_reach_provider_panel_not_just_direct_evaluator(self):
        from hybrid_engine.provider_bridge import ProviderBridge,nba_provider_panel
        from hybrid_engine.provider_access import ProviderAccess
        from tests.test_provider_bridge import FakeProvider,SECRET,NOW
        bridge=ProviderBridge(ProviderAccess({'THE_ODDS_API':SECRET},getter=FakeProvider(),clock=lambda:NOW),
            self.h.root/'provider',clock=lambda:NOW,rule_book=self.book())
        snapshot=dict(self.h.snap,parameter_fit_cutoff_utc=NOW-60)
        with patch('hybrid_engine.market_views.replay_nba',return_value=self.h.dist):
            panel=nba_provider_panel(snapshot,None,bridge,structured=True)
        self.assertIn('Ham model beklenen getirisi',panel['html'])
        self.assertEqual(panel['market_source_status'],'OBSERVED_RULES_AND_CALIBRATION_PENDING')
        self.assertGreater(panel['market_native_observations'],0)
        self.assertGreater(len(panel['cards']),0)
        self.assertTrue(all(c['calibration_status']=='NOT_CALIBRATED' for c in panel['cards']))


class CycleTests(IsolatedAsyncioTestCase):
    async def test_user_fixture_priority_runs_before_v2_without_telegram_fit(self):
        order=[]
        async def v2():
            order.append('v2')
            return dict(status='CHECKED')
        def tick(*,preferred_fixture_id=None):
            order.append('current:'+str(preferred_fixture_id))
            return dict(status='CHECKED',requested_fixture_status='PUBLISHED_OR_REPLAYED')
        app=SimpleNamespace(bot_data={})
        cycle=ResearchCycle(SimpleNamespace(tick=v2),None,SimpleNamespace(tick=tick))
        requested_at=1795339800
        with patch('hybrid_engine.research_diagnostics.time.time',return_value=requested_at):
            self.assertTrue(cycle.request_fixture(dict(league='NBA',fixture_id='requested-nba-match',
                fixture_start_utc=requested_at+7200)))
            self.assertTrue(cycle.request_fixture(dict(league='NBA',fixture_id='requested-nba-match',
                fixture_start_utc=requested_at+7200)))
            self.assertEqual(len(cycle.requested_fixtures),1)
            await cycle.once(app)
        self.assertEqual(order,['current:requested-nba-match','v2'])
        self.assertEqual(cycle.requested_fixtures,[])
        self.assertEqual(app.bot_data['last_current_assessment_poll']['status'],'CHECKED')

    async def test_requested_fixture_retries_after_abstain_then_clears_only_on_publication(self):
        outcomes=iter(('FAILED_OR_ABSTAIN','PUBLISHED_OR_REPLAYED'))
        seen=[]
        async def v2():return dict(status='CHECKED')
        def current(*,preferred_fixture_id=None):
            result=next(outcomes)
            seen.append((preferred_fixture_id,result))
            return dict(status='PARTIAL_ABSTAIN' if result=='FAILED_OR_ABSTAIN' else 'CHECKED',
                        requested_fixture_status=result)
        t=1795339800
        app=SimpleNamespace(bot_data={})
        cycle=ResearchCycle(SimpleNamespace(tick=v2),None,SimpleNamespace(tick=current))
        with patch('hybrid_engine.research_diagnostics.time.time',return_value=t):
            self.assertTrue(cycle.request_fixture(dict(league='NBA',fixture_id='ind-okc',
                fixture_start_utc=t+7200)))
            await cycle.once(app)
            self.assertEqual(cycle.requested_fixtures,['ind-okc'])
            self.assertEqual(app.bot_data['last_current_assessment_poll']['requested_fixture_status'],
                             'FAILED_OR_ABSTAIN')
            await cycle.once(app)
        self.assertEqual(seen,[('ind-okc','FAILED_OR_ABSTAIN'),('ind-okc','PUBLISHED_OR_REPLAYED')])
        self.assertEqual(cycle.requested_fixtures,[])
        self.assertEqual(cycle.requested_deadlines,{})

    async def test_requested_fixture_expiry_never_retries_after_cutoff(self):
        called=[]
        async def v2():return dict(status='CHECKED')
        def current(*,preferred_fixture_id=None):
            called.append(preferred_fixture_id)
            return dict(status='CHECKED',requested_fixture_status='FAILED_OR_ABSTAIN')
        t=1795339800
        app=SimpleNamespace(bot_data={})
        cycle=ResearchCycle(SimpleNamespace(tick=v2),None,SimpleNamespace(tick=current))
        with patch('hybrid_engine.research_diagnostics.time.time',return_value=t):
            self.assertTrue(cycle.request_fixture(dict(league='NBA',fixture_id='expires',
                fixture_start_utc=t+1800)))
            await cycle.once(app)
        self.assertEqual(cycle.requested_fixtures,['expires'])
        with patch('hybrid_engine.research_diagnostics.time.time',return_value=t+1501):
            await cycle.once(app)
        self.assertEqual(called,['expires',None])
        self.assertEqual(cycle.requested_fixtures,[])
        self.assertEqual(cycle.requested_deadlines,{})

    async def test_current_score_precedes_v2_and_study_failure_does_not_starve_stages(self):
        order=[]
        def v3():order.append('v3');raise ValueError('DYNAMIC_RECENT_TEAM_HISTORY_REQUIRED')
        async def v2():order.append('v2');return dict(status='CHECKED')
        def current():order.append('current');return dict(status='CHECKED')
        worker=SimpleNamespace(tick=v2);study=SimpleNamespace(tick=v3,last_report=None)
        cycle=ResearchCycle(worker,study,SimpleNamespace(tick=current));app=SimpleNamespace(bot_data={})
        await cycle.once(app)
        self.assertEqual(order,['current','v2','v3']);self.assertIn('FAILED',cycle.render())
        self.assertIn('DYNAMIC_RECENT_TEAM_HISTORY_REQUIRED',cycle.render())
        self.assertEqual(app.bot_data['last_current_assessment_poll']['status'],'CHECKED')

    async def test_current_publication_runs_before_a_blocked_v2_stage(self):
        # V2 must not consume the only remaining pre-tipoff publication window.
        entered=asyncio.Event();blocked=asyncio.Event();order=[]
        async def v2():
            order.append('v2-start')
            entered.set()
            await blocked.wait()
        def current(*,preferred_fixture_id=None):
            order.append('current')
            return dict(status='CHECKED',requested_fixture_status='PUBLISHED_OR_REPLAYED')
        cycle=ResearchCycle(SimpleNamespace(tick=v2),None,SimpleNamespace(tick=current))
        app=SimpleNamespace(bot_data={})
        task=asyncio.create_task(cycle.once(app))
        try:
            await asyncio.wait_for(entered.wait(),timeout=2)
            self.assertEqual(order[:2],['current','v2-start'])
            self.assertEqual(app.bot_data['last_current_assessment_poll']['status'],'CHECKED')
            self.assertEqual(cycle.stages['current_assessment']['status'],'COMPLETED')
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_shadow_blocker_visible_before_v2_and_witness_refreshed_after_v2(self):
        order=[]
        async def v2():order.append("v2");return dict(status="CHECKED")
        def witness(folder):
            order.append("player_shadow")
            self.assertEqual(str(folder),"isolated/player-shadow")
            return dict(status="BLOCKED_NO_PROSPECTIVE_PLAYER_MINUTES",
                        prospective_minutes_games=0,prepared_artifacts=0,
                        production_enabled=False)
        worker=SimpleNamespace(tick=v2,research=SimpleNamespace(players="isolated/player-shadow"))
        cycle=ResearchCycle(worker,None);app=SimpleNamespace(bot_data={})
        with patch("hybrid_engine.player_shadow.readiness",side_effect=witness):
            await cycle.once(app)
        self.assertEqual(order,["player_shadow","v2","player_shadow"])
        self.assertEqual(cycle.stages["player_shadow"]["status"],"COMPLETED")
        self.assertEqual(app.bot_data["last_player_shadow_poll"]["prospective_minutes_games"],0)
        self.assertNotIn("player_model_published",app.bot_data)

    async def test_running_stage_is_visible_and_cancellation_does_not_start_parallel_fits(self):
        entered=asyncio.Event();gate=asyncio.Event()
        async def v2():entered.set();await gate.wait()
        cycle=ResearchCycle(SimpleNamespace(tick=v2),None);app=SimpleNamespace(bot_data={})
        task=asyncio.create_task(cycle.once(app));await entered.wait()
        self.assertIn('RUNNING',cycle.render());task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(cycle.stages['adaptive_v2']['status'],'CANCELLED')

    async def test_analysis_display_reads_assessment_and_keeps_original_snapshot(self):
        response=dict(status='ANALYSIS_OK',snapshot=dict(fixture_id='original'),html='Original',html_parts=['Original'])
        base=SimpleNamespace(analyze=AsyncMock(return_value=response),ledger=object())
        assessor=SimpleNamespace(render=Mock(return_value='GÜNCEL ARAŞTIRMA DEĞERLENDİRMESİ'))
        state=dict(verified_analysis_service=base)
        install_display(state,assessor)
        out=await state['verified_analysis_service'].analyze('NBA','day','A','B')
        self.assertIn('GÜNCEL',out['html']);self.assertIs(out['snapshot'],response['snapshot'])
        self.assertEqual(response['html'],'Original');assessor.render.assert_called_once_with(response['snapshot'])


class TelegramRevisionTests(IsolatedAsyncioTestCase):
    async def test_real_ptb_analyze_handler_displays_archived_current_model_without_refit(self):
        from tests import test_europe_premium_ui as ui
        from telegram import Update
        await ui.EuropeanButtonTests.asyncSetUp(self)
        h=AssessmentTests('runTest');h.setUp();self.addCleanup(h.doCleanups)
        p,_=h.capture();before=h.files()
        response=dict(status='ANALYSIS_OK',snapshot=h.original,html='İLK TAHMİN',html_parts=['İLK TAHMİN'],
            timeline=dict(prediction_generated_at_utc=h.h.now,first_archived_at_utc=h.h.now,
                snapshot_created_at_utc=h.h.now,tipoff_utc=h.target['fixture_start_utc'],reused_forecast=True))
        self.app.bot_data['verified_analysis_service']=SimpleNamespace(analyze=AsyncMock(return_value=response))
        install_display(self.app.bot_data,h.assess)
        text='/analyze NBA 2026-11-20 Home Test vs Away Test'
        update=Update.de_json(dict(update_id=501,message=dict(message_id=501,date=h.h.now,
            chat=dict(id=17,type='private'),**{'from':dict(id=23,is_bot=False,first_name='Synthetic')},
            text=text,entities=[dict(type='bot_command',offset=0,length=8)])),self.app.bot)
        with patch('hybrid_engine.nba_dynamic.predict',side_effect=AssertionError('NO_HANDLER_INFERENCE')):
            await self.app.process_update(update)
        sent='\n'.join(self.api.sent)
        self.assertIn('GÜNCEL ARAŞTIRMA DEĞERLENDİRMESİ',sent)
        self.assertIn(f"Toplam {p['candidate']['total']:.2f}",sent);self.assertIn('İLK TAHMİN',sent)
        self.assertEqual(before,h.files());self.assertFalse(any(len(s.encode('utf-16-le'))//2>4096 for s in self.api.sent))
