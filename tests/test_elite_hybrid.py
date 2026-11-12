"""Mechanics fixtures, never evidence of live delivery or model accuracy."""
import asyncio
from copy import deepcopy
from datetime import datetime,timezone
from html.parser import HTMLParser
import importlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase,IsolatedAsyncioTestCase
from unittest.mock import AsyncMock,Mock,patch

import numpy as np

from hybrid_engine.distributions import Forecast
from hybrid_engine.intervals import prediction_intervals,empirical_coverage,assert_frozen_sampler_sources
from hybrid_engine.elite_render import render_elite,split_blocks,units
from hybrid_engine.confidence import confidence_index
from hybrid_engine.frozen_archive import FrozenArchive,FrozenHybridService,read_gzip
from hybrid_engine.test_bot import configuration
from telegram_delivery import timeline

ARCHIVE=Path(__file__).resolve().parents[1]/'docs/prospective/euroleague-20261112'


def synthetic_forecast():
    a=np.empty((10000,4,2),dtype=np.int32);a[:5000]=[25,24];a[5000:]=[30,20]
    return Forecast('SYNTHETIC_RESOURCE_ONLY',a.mean(axis=0),samples=a,metadata=dict(method='SYNTHETIC',seed=1))


class IntervalTests(TestCase):
    def test_quantiles_are_computed_from_actual_paths_for_all_required_markets(self):
        b=prediction_intervals(synthetic_forecast());q=b['markets']['TOTAL']
        self.assertEqual(b['scenarios'],10000);self.assertEqual(q['p50'],198)
        self.assertEqual(q['p25'],196);self.assertEqual(q['p75'],200)
        self.assertEqual(len(b['markets']),11)
        self.assertEqual(b['markets']['HOME_HANDICAP']['p05'],-b['markets']['MARGIN']['p95'])

    def test_analytic_forecast_has_no_fabricated_sample_interval(self):
        b=prediction_intervals(Forecast('SYNTHETIC',np.ones((4,2))))
        self.assertEqual(b['status'],'UNSUPPORTED');self.assertEqual(b['markets'],{})

    def test_actual_sample_hash_and_nested_bands_are_deterministic(self):
        f=synthetic_forecast();a=prediction_intervals(f);b=prediction_intervals(f)
        self.assertEqual(a,b)
        for q in a['markets'].values():self.assertLessEqual(q['p05'],q['p25']);self.assertLessEqual(q['p75'],q['p95'])
        expected=np.corrcoef(f.samples.sum(axis=1),rowvar=False)
        np.testing.assert_allclose(a['simulated_correlations']['team_scores'],expected,atol=1e-12)

    def test_observed_coverage_is_not_nominal_probability(self):
        b=prediction_intervals(synthetic_forecast())
        r=empirical_coverage([(b,dict(home=[50]*4,away=[50]*4))])
        total=r['markets']['TOTAL']['P25_P75']
        self.assertEqual(total['n'],1);self.assertEqual(total['observed_coverage'],0)
        self.assertEqual(total['nominal_mass'],.5);self.assertGreater(total['wilson_95'][1],0)

    def test_frozen_native_sampler_sources_remain_identical(self):
        archive=FrozenArchive(ARCHIVE)
        for r in archive.records.values():assert_frozen_sampler_sources(r)

    def test_chunk_reader_refuses_decompression_over_budget(self):
        import gzip
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'source.gz';p.write_bytes(gzip.compress(b'x'*100000))
            with self.assertRaisesRegex(ValueError,'SIZE_BUDGET'):read_gzip(p,maximum=50000)


class ConfidenceAndFormatTests(TestCase):
    def context(self):
        return dict(prediction_utc=1736400000,model_digest='fixture-model',market='TOTAL',line=200.5,
            probabilities=[.9,.05,.05],minimum_team_history=10,verified_roster_and_rotation=True,
            relative_interval_width=.2,model_disagreement=.1)

    def test_raw_event_probability_does_not_become_confidence(self):
        r=confidence_index(context=self.context());self.assertIsNone(r['value'])
        self.assertIn('NO_VERIFIED_DISJOINT_CALIBRATION',r['reasons'])

    def test_quality_index_requires_a_prior_disjoint_profile_and_error_audit(self):
        from tests.test_hybrid_acceptance import calibration_records
        from hybrid_engine.markets import MarketCalibration
        a,b=calibration_records();profile=MarketCalibration.fit(a,b,model_digest='fixture-model',market='TOTAL',line=200.5,cutoff_utc=1736300000)
        history=dict(role='PRIOR_AUDIT',n=200,available_max_utc=1736300000,model_digest='fixture-model',mae=5,interval_coverage_90=.9)
        r=confidence_index(context=self.context(),calibration=profile,history=history)
        self.assertIsNotNone(r['value']);self.assertGreaterEqual(r['value'],0);self.assertLessEqual(r['value'],100)
        event_bound=profile.apply([.9,.05,.05],model_digest='fixture-model',market='TOTAL',line=200.5,prediction_utc=1736400000)['confidence_index']
        self.assertNotEqual(r['components']['calibration'],event_bound)
        history['available_max_utc']=1736500000
        self.assertIsNone(confidence_index(context=self.context(),calibration=profile,history=history)['value'])

    def test_phone_messages_keep_valid_html_and_utf16_budget(self):
        archive=FrozenArchive(ARCHIVE);r=deepcopy(next(iter(archive.records.values())))
        r['fixture']['home_name']='<script>'+('&'*220)
        r['fixture']['away_name']='&'*220
        f=synthetic_forecast();parts=render_elite(r,f,prediction_intervals(f),{'value':None})
        self.assertGreater(len(parts),1);self.assertTrue(all(units(p)<=3200 for p in parts))
        class Parser(HTMLParser):
            def __init__(self):super().__init__();self.stack=[]
            def handle_starttag(self,t,a):self.stack.append(t)
            def handle_endtag(self,t):self.assert_tag=t;assert self.stack.pop()==t
        for part in parts:
            p=Parser();p.feed(part);self.assertEqual(p.stack,[]);self.assertNotIn('<script>',part)

    def test_splitter_never_splits_html_inside_a_block(self):
        parts=split_blocks(['<b>'+('x'*1800)+'</b>']*3)
        self.assertEqual(len(parts),3)
        with self.assertRaises(ValueError):split_blocks(['x'*3201])

    def test_test_bot_preflight_never_uses_production_token_as_fallback(self):
        c=configuration({'TELEGRAM_BOT_TOKEN':'DO_NOT_USE'})
        self.assertEqual(c['status'],'NOT_CONFIGURED');self.assertIn('ZEYNAL_TEST_BOT_TOKEN',c['missing'])

    def test_test_bot_identity_requires_expected_id_and_test_username(self):
        env=dict(ZEYNAL_TEST_BOT_TOKEN='123456:TEST',ZEYNAL_TEST_BOT_ID='123456',ZEYNAL_TEST_BOT_USERNAME='zeynal_test_bot',ZEYNAL_TEST_CHAT_ID='17')
        self.assertEqual(configuration(env)['status'],'CONFIGURED_NOT_TESTED')
        env['ZEYNAL_TEST_BOT_USERNAME']='production_bot'
        with self.assertRaises(ValueError):configuration(env)


class LifecycleTests(IsolatedAsyncioTestCase):
    async def test_duplicate_update_does_not_resend_an_already_accepted_message(self):
        from telegram_delivery import DeliveryJournal,reply_analysis
        with TemporaryDirectory() as tmp:
            journal=DeliveryJournal(Path(tmp)/'d.sqlite')
            message=SimpleNamespace(text='/analyze same',reply_text=AsyncMock(return_value=SimpleNamespace(date=datetime.now(timezone.utc),message_id=1)))
            update=SimpleNamespace(update_id=1,effective_chat=SimpleNamespace(id=17),message=message)
            context=SimpleNamespace(application=SimpleNamespace(bot_data={'delivery_journal':journal}))
            await reply_analysis(update,context,dict(html='a'),SimpleNamespace())
            await reply_analysis(update,context,dict(html='a'),SimpleNamespace())
            self.assertEqual(message.reply_text.call_count,1);self.assertEqual(len(journal.read()),2)

    async def test_same_update_id_cannot_silently_change_the_user_request(self):
        from telegram_delivery import DeliveryJournal,reply_analysis
        with TemporaryDirectory() as tmp:
            journal=DeliveryJournal(Path(tmp)/'d.sqlite')
            message=SimpleNamespace(text='/analyze first',reply_text=AsyncMock(return_value=SimpleNamespace(date=datetime.now(timezone.utc),message_id=1)))
            update=SimpleNamespace(update_id=1,effective_chat=SimpleNamespace(id=17),message=message)
            context=SimpleNamespace(application=SimpleNamespace(bot_data={'delivery_journal':journal}))
            await reply_analysis(update,context,dict(html='a'),SimpleNamespace());message.text='/analyze changed'
            with self.assertRaisesRegex(ValueError,'UPDATE_ID_CONFLICT'):await reply_analysis(update,context,dict(html='b'),SimpleNamespace())
            self.assertEqual(message.reply_text.call_count,1)

    async def test_partial_send_timeout_keeps_first_delivery_and_never_retries_it(self):
        from telegram_delivery import DeliveryJournal,reply_analysis
        with TemporaryDirectory() as tmp:
            journal=DeliveryJournal(Path(tmp)/'delivery.sqlite')
            message=SimpleNamespace(reply_text=AsyncMock(side_effect=[SimpleNamespace(date=datetime.now(timezone.utc),message_id=1),TimeoutError()]))
            update=SimpleNamespace(update_id=1,effective_chat=SimpleNamespace(id=17),message=message)
            ctx=SimpleNamespace(application=SimpleNamespace(bot_data={'delivery_journal':journal}))
            with self.assertRaises(TimeoutError):await reply_analysis(update,ctx,dict(html='a',html_parts=['a','b']),SimpleNamespace())
            events=journal.read();self.assertEqual(message.reply_text.call_count,2)
            self.assertEqual(events[1]['status'],'TELEGRAM_ACCEPTED');self.assertEqual(events[-1]['status'],'NOT_CONFIRMED')
            self.assertEqual(events[-1]['part_index'],1)

    async def test_disk_failure_prevents_an_unjournaled_send(self):
        from telegram_delivery import DeliveryJournal,reply_analysis
        import sqlite3
        with TemporaryDirectory() as tmp:
            journal=DeliveryJournal(Path(tmp)/'delivery.sqlite');message=SimpleNamespace(reply_text=AsyncMock())
            update=SimpleNamespace(update_id=2,effective_chat=SimpleNamespace(id=17),message=message)
            ctx=SimpleNamespace(application=SimpleNamespace(bot_data={'delivery_journal':journal}))
            with patch.object(journal,'append',side_effect=sqlite3.OperationalError('synthetic disk full')):
                with self.assertRaises(sqlite3.OperationalError):await reply_analysis(update,ctx,dict(html='x'),SimpleNamespace())
            message.reply_text.assert_not_called()

    async def test_cached_v1_forecast_reuses_the_first_record_and_durable_time(self):
        from tests.test_release_integration import nba_fetcher,NOW,LiveAnalysisLedger,VerifiedAnalyzeService
        with TemporaryDirectory() as tmp:
            with patch('time.time',return_value=NOW):
                service=VerifiedAnalyzeService(LiveAnalysisLedger(Path(tmp)/'test.sqlite'),nba_fetcher())
                first=await service.analyze('NBA','2026-11-11','SH','Synthetic Bears')
            self.assertEqual(first['status'],'ANALYSIS_OK');p=first['snapshot']
            service.identity.preflight=AsyncMock(return_value=dict(status='VERIFIED_NBA_FIXTURE',league='NBA',season_id='2026/2027',
                fixture=dict(canonical_id=p['fixture_id'],start_ts_utc=p['fixture_start_utc'])))
            with patch('time.time',return_value=NOW+1200):second=await service.analyze('NBA','2026-11-11','SH','Synthetic Bears')
            self.assertFalse(second['new_record']);self.assertEqual(first['snapshot'],second['snapshot'])
            t=timeline(second,service,NOW+1200)
            self.assertEqual(t['first_archived_at_utc'],NOW);self.assertEqual(t['response_prepared_at_utc'],NOW+1200)
            self.assertIsNone(t['prediction_generated_at_utc'])

    async def test_after_tipoff_hybrid_replay_is_explicit_and_read_only(self):
        archive=FrozenArchive(ARCHIVE);r=next(iter(archive.records.values()));g=r['fixture']
        before={p:p.read_bytes() for p in ARCHIVE.iterdir()}
        with patch('time.time',return_value=g['start_ts_utc']+10000):
            result=await FrozenHybridService(archive).analyze('EUROLEAGUE','2026-11-12',g['home_name'],g['away_name'])
        self.assertEqual(result['status'],'FROZEN_REPLAY_OK');self.assertFalse(result['new_record'])
        self.assertIn('PREMATCH tahmini değildir','\n'.join(result['html_parts']))
        self.assertTrue(all(p.read_bytes()==b for p,b in before.items()))


class CommandScenarioTests(IsolatedAsyncioTestCase):
    async def exercise(self,command,scenario):
        with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'123456:SYNTHETIC_ONLY'}):main=importlib.import_module('main')
        from nba_command import nba_command
        from ledger_reports import accuracy_command,compare_command
        msg=SimpleNamespace(text='/analyze NBA 2026-11-13 Synthetic Home vs Synthetic Away',reply_text=AsyncMock(return_value=SimpleNamespace(date=datetime.now(timezone.utc),message_id=1)))
        update=SimpleNamespace(message=msg,effective_message=msg,effective_chat=SimpleNamespace(id=17),update_id=10)
        row=dict(league='NBA',fixture_id='x',home='Synthetic Home',away='Synthetic Away',model_version='SYNTHETIC',model_digest='0'*64,prediction=[100,99],actual=None)
        report=dict(status='VERIFIED_LIVE_REPORT',groups=[],unique_fixtures=1,pending=1,forecasts=[row])
        read=Mock(return_value=report);analyze=AsyncMock(return_value=dict(html='<b>SYNTHETIC RESULT</b>'))
        loader=AsyncMock(return_value=[dict(id='synthetic',start=datetime.now(timezone.utc),home='Synthetic Home',away='Synthetic Away',status='Başlamadı')])
        args={'nba':['2026-11-13'],'analyze':[],'accuracy':['NBA'],'compare':['NBA','x']}[command]
        if scenario=='missing':
            loader.return_value=[];analyze.return_value=dict(status='ABSTAIN',html='Veri eksik. Tahmin üretilmedi.');report['forecasts']=[]
        elif scenario in ('service_error','timeout'):
            exc=RuntimeError('INTERNAL_PRIVATE_MARKER') if scenario=='service_error' else TimeoutError('INTERNAL_PRIVATE_MARKER')
            loader.side_effect=exc;analyze.side_effect=exc;read.side_effect=exc
        elif scenario=='wrong_parameters':
            args={'nba':['bad-date'],'analyze':[],'accuracy':['NBA','extra'],'compare':['NBA']}[command]
            msg.text='/analyze bad'
        ctx=SimpleNamespace(args=args,application=SimpleNamespace(bot_data=dict(nba_fixture_loader=loader,
            verified_analysis_service=SimpleNamespace(analyze=analyze),ledger_reports=SimpleNamespace(read=read))))
        await {'nba':nba_command,'analyze':main.analyze_command,'accuracy':accuracy_command,'compare':compare_command}[command](update,ctx)
        self.assertTrue(msg.reply_text.called)
        self.assertTrue(all('INTERNAL_PRIVATE_MARKER' not in c.args[0] for c in msg.reply_text.call_args_list))


def scenario_test(command,scenario):
    async def test(self):await self.exercise(command,scenario)
    return test


for _command in ('nba','analyze','accuracy','compare'):
    for _scenario in ('success','missing','wrong_parameters','service_error','timeout'):
        setattr(CommandScenarioTests,'test_'+_command+'_'+_scenario,scenario_test(_command,_scenario))
