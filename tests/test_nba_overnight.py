"""Synthetic ESPN receipts + real inference/registered capture, not Telegram E2E."""
import asyncio
from copy import deepcopy
from datetime import datetime,timezone
import json
import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase,TestCase
from unittest.mock import AsyncMock,Mock,patch

from core.team_identity import digest
from hybrid_engine.challenger_forward import register,load_plan,admission
from hybrid_engine.forward_validation import ForwardRegistry
from hybrid_engine.live_nba import LiveNBAHybridService
from hybrid_engine.nba_overnight import NBAOvernightScheduler,PrematchDeadlineLedger,upcoming,LOOKAHEAD
from live_analysis_ledger import LiveAnalysisLedger
from tests.test_phase843 import synthetic_prepared
from tests.test_release_integration import nba_fetcher,live_payload
from tests.test_season_archive_audit import NOW
from verified_analysis import VerifiedAnalyzeService

START=NOW+8*3600  # Evening 19:00 TSİ -> next day's 03:00 TSİ.


class NBAOvernightTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.now=NOW;timer=patch('time.time',side_effect=lambda:self.now);timer.start();self.addCleanup(timer.stop)
        self.prepared=synthetic_prepared(self.root/'prepared.json')
        base=nba_fetcher();self.offline=False;self.status='STATUS_SCHEDULED'
        def source(provider,url):
            if self.offline:return dict(status='SOURCE_RATE_LIMITED',http_status=429)
            r=base(provider,url);r['observed_at_utc']=self.now-2;r['ingested_at_utc']=self.now-1
            if '/scoreboard?' in url:
                for e in r['document']['events']:
                    e['date']=datetime.fromtimestamp(START,timezone.utc).isoformat()
                    e['status']['type']['name']=self.status
                    e['competitions'][0]['status']['type']['name']=self.status
                    for side in e['competitions'][0]['competitors']:
                        side['team']['displayName']='Synthetic Hawks' if side['team']['id']=='1' else 'Synthetic Bears'
                        side['score']='0';side.pop('linescores',None)
            r['document_sha256']=digest(r['document']);return r
        self.fetch=Mock(side_effect=source)
        self.service=LiveNBAHybridService(self.root/'live',self.prepared,fetcher=self.fetch)
        self.plan_path=self.root/'research'/'protocol'
        self.now=NOW-1;self.plan,_=register(self.plan_path);self.now=NOW
        self.loader=VerifiedAnalyzeService(None,fetcher=self.fetch).list_nba_games
        self.scheduler=NBAOvernightScheduler(self.service,self.loader,self.root/'overnight',self.plan_path,clock=lambda:self.now)

    async def test_evening_boot_archives_next_day_nba_and_acceptance_without_waiting_for_tipoff(self):
        before=next(self.plan_path.glob('plan-*')).read_bytes()
        with patch('hybrid_engine.models.HierarchicalStrength.fit',side_effect=AssertionError('NO ACTIVE MODEL REFIT')):
            r=await self.scheduler.tick()
        self.assertEqual(r['predictions'][0]['status'],'ARCHIVED',r)
        self.assertEqual(r['acceptance']['results'][0]['status'],'ARCHIVED',r)
        self.assertEqual(r['progress']['pending'],1)
        self.assertEqual(before,next(self.plan_path.glob('plan-*')).read_bytes())
        from hybrid_engine.forward_nba_results import read_confirmed
        p=read_confirmed(self.service.ledger.path)[0]['snapshot']
        self.assertGreater(p['fixture_start_utc']-p['prediction_generated_at_utc'],6*3600)
        self.assertEqual(p['intervals']['scenarios'],10000);self.assertIsNone(p['confidence']['value'])
        self.assertIsNone(admission(p,self.plan,self.now))
        records=ForwardRegistry(self.plan_path/'forecasts').records();self.assertEqual(len(records),1)
        self.assertEqual(records[0]['payload']['version'],self.plan['sha256'])
        self.assertEqual(records[0]['payload']['experiment']['components']['UPDATED_BAYES_STOCHASTIC_PERIODS']['status'],'AVAILABLE')
        self.assertFalse(r['actual_telegram_delivery_verified']);self.assertFalse(r['calibration_fit'])

    async def test_restart_and_retries_preserve_first_forecast_and_registered_protocol(self):
        first=await self.scheduler.tick();before=self.service.ledger.path.read_bytes()
        source_files={p.name:p.read_bytes() for p in self.service.assets.iterdir()}
        registry=ForwardRegistry(self.plan_path/'forecasts');pin=digest(registry.records()[0]['payload'])
        restart=NBAOvernightScheduler(self.service,self.loader,self.root/'overnight',self.plan_path,clock=lambda:self.now)
        with patch.object(self.service,'_predict',side_effect=AssertionError('NO REGENERATION')):r=await restart.tick(force=True)
        self.assertEqual(r['predictions'],[]);self.assertEqual(r['already_archived'],1)
        self.assertEqual(before,self.service.ledger.path.read_bytes());self.assertEqual(pin,digest(registry.records()[0]['payload']))
        self.assertEqual(source_files,{p.name:p.read_bytes() for p in self.service.assets.iterdir()})
        self.assertEqual(first['acceptance']['protocol_sha256'],load_plan(self.plan_path)['sha256'])

    async def test_fresh_manual_telegram_style_prediction_is_captured_in_background(self):
        result=await self.service.analyze('NBA','2026-11-12','Synthetic Hawks','Synthetic Bears')
        self.assertEqual(result['status'],'ANALYSIS_OK',result);before=self.service.ledger.path.read_bytes()
        r=await self.scheduler.tick()
        self.assertEqual(r['predictions'],[]);self.assertEqual(r['acceptance']['results'][0]['status'],'ARCHIVED')
        self.assertEqual(before,self.service.ledger.path.read_bytes())

    async def test_old_original_is_preserved_and_not_retimed_to_satisfy_acceptance(self):
        result=await self.service.analyze('NBA','2026-11-12','Synthetic Hawks','Synthetic Bears')
        self.assertEqual(result['status'],'ANALYSIS_OK',result);before=self.service.ledger.path.read_bytes()
        self.now+=3601;r=await self.scheduler.tick(force=True)
        self.assertEqual(r['predictions'],[])
        self.assertEqual(r['acceptance']['skipped']['ORIGINAL_INPUTS_TOO_OLD_FOR_PROTOCOL'],1)
        self.assertEqual(r['progress']['pending'],0);self.assertEqual(before,self.service.ledger.path.read_bytes())

    async def test_missing_protocol_is_explicit_but_does_not_fabricate_registration(self):
        self.scheduler.protocol=self.root/'missing-protocol'
        r=await self.scheduler.tick();self.assertEqual(r['predictions'][0]['status'],'ARCHIVED')
        self.assertEqual(r['status'],'PARTIAL_ABSTAIN');self.assertEqual(r['acceptance']['status'],'ABSTAIN')
        self.assertFalse(self.scheduler.protocol.exists())

    async def test_source_failure_and_recovery_never_claims_a_forecast_for_a_failed_fetch(self):
        self.offline=True;r=await self.scheduler.tick();self.assertEqual(r['status'],'PARTIAL_ABSTAIN')
        self.assertEqual(r['predictions'],[]);self.assertEqual(self.service.ledger.integrity()['snapshots'],0)
        self.offline=False;self.now+=301;r=await self.scheduler.tick()
        self.assertEqual(r['predictions'][0]['status'],'ARCHIVED',r)

    async def test_postponed_fixture_is_not_admitted(self):
        self.status='STATUS_POSTPONED';r=await self.scheduler.tick()
        self.assertEqual(r['predictions'],[]);self.assertEqual(self.service.ledger.integrity()['snapshots'],0)

    async def test_last_5_minutes_and_started_games_never_create_early_records(self):
        for at in (START-300,START-1,START+1):
            self.now=at;r=await self.scheduler.tick(force=True)
            self.assertEqual(r['predictions'],[]);self.assertEqual(self.service.ledger.integrity()['snapshots'],0)

    async def test_capture_failure_does_not_destroy_original_or_publish_fake_progress(self):
        with patch.object(self.scheduler,'capture',side_effect=ValueError('SYNTHETIC_PRIVATE_DETAIL')):r=await self.scheduler.tick()
        self.assertEqual(self.service.ledger.integrity()['snapshots'],1)
        self.assertEqual(r['status'],'PARTIAL_ABSTAIN');self.assertNotIn('SYNTHETIC_PRIVATE_DETAIL',json.dumps(r))
        self.assertEqual(r['progress']['pending'],0)

    async def test_run_is_cancellable_without_stopping_user_facing_bot(self):
        app=SimpleNamespace(bot_data={})
        task=asyncio.create_task(self.scheduler.run(app))
        deadline=asyncio.get_running_loop().time()+15
        while not app.bot_data and asyncio.get_running_loop().time()<deadline:await asyncio.sleep(.01)
        self.assertIn('last_nba_overnight_poll',app.bot_data)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertFalse(self.scheduler.running)

    async def test_overlapping_ticks_are_rejected_without_duplicate_capture(self):
        self.scheduler.running=True;r=await self.scheduler.tick()
        self.assertEqual(r['status'],'ABSTAIN');self.assertEqual(self.service.ledger.integrity()['snapshots'],0)


class NBAWindowAndCommitTests(TestCase):
    def test_commit_boundary_is_atomic_and_old_record_remains_readable(self):
        with TemporaryDirectory() as tmp,patch('time.time',return_value=NOW):
            ledger=PrematchDeadlineLedger(LiveAnalysisLedger(Path(tmp)/'nba.sqlite'))
            p,new=ledger.commit(live_payload(NOW+901));self.assertTrue(new)
            self.assertEqual(p['record_deadline_utc'],NOW+1)
            with patch('time.time',return_value=NOW+2):
                with self.assertRaises(ValueError):ledger.commit(live_payload(NOW+901))
                self.assertEqual(ledger.get(p['league'],p['fixture_id'],p['model_digest']),p)

    def test_overnight_age_policy_is_not_a_one_hour_before_tipoff_requirement(self):
        p=dict(feature_cutoff_utc=NOW,prediction_generated_at_utc=NOW,fixture_start_utc=NOW+LOOKAHEAD)
        self.assertIsNone(admission(p,dict(payload=dict(registered_at_utc=NOW-1)),NOW))


class NBAFixtureWindowTests(IsolatedAsyncioTestCase):
    async def test_lookahead_is_bounded_tsi_day_preserved_and_duplicates_not_counted(self):
        at=NOW;row=dict(id='401000123',start=datetime.fromtimestamp(NOW+3600,timezone.utc),home='A',away='B',status='Başlamadı')
        far=dict(row,id='401000124',start=datetime.fromtimestamp(NOW+LOOKAHEAD+1,timezone.utc))
        loader=AsyncMock(return_value=[row,far]);rows=await upcoming(loader,at)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['day'],'2026-11-11')
        self.assertLessEqual(loader.call_count,3)
        with self.assertRaises(ValueError):await upcoming(AsyncMock(return_value=[dict(row,start=datetime(2026,11,11))]),at)

    async def test_conflicting_native_ids_refused_instead_of_taking_the_last_partition(self):
        row=dict(id='401000123',start=datetime.fromtimestamp(NOW+3600,timezone.utc),home='A',away='B',status='Başlamadı')
        with self.assertRaises(ValueError):await upcoming(AsyncMock(return_value=[row,dict(row,away='C')]),NOW)


class NBAOvernightTelegramTests(IsolatedAsyncioTestCase):
    async def test_overnight_capture_and_progress_are_wired_to_real_ptb_handlers_without_broadcast(self):
        import importlib
        from aiohttp import web
        from telegram import Update
        from telegram.ext import Application
        from telegram_delivery import DeliveryJournal
        from hybrid_engine.frozen_archive import FrozenArchive
        from hybrid_engine.test_bot import install_isolated_services,AuditedRequest
        from tests.test_phase843 import ROOT
        archive=FrozenArchive(ROOT/'docs/prospective/euroleague-20261112')
        # Register fixture cleanups on this running test's asyncio runner.
        # An unstarted IsolatedAsyncioTestCase cannot execute its own cleanups.
        fixture=SimpleNamespace(addCleanup=self.addCleanup)
        await NBAOvernightTests.asyncSetUp(fixture)
        root=fixture.root/'application';plan=root/'challenger-research/protocol';plan.mkdir(parents=True)
        for f in fixture.plan_path.glob('plan-*'):shutil.copy2(f,plan/f.name)
        sent=[]
        async def api(request):
            method=request.path.rsplit('/',1)[-1]
            if method=='getMe':result=dict(id=123456,is_bot=True,first_name='Synthetic',username='zeynal_test_bot')
            elif method=='sendMessage':
                p=dict(await request.post());sent.append(p['text'])
                result=dict(message_id=100+len(sent),date=fixture.now,chat=dict(id=17,type='private'),text=p['text'])
            else:result=True
            return web.json_response(dict(ok=True,result=result))
        server=web.Application();server.router.add_route('*','/{path:.*}',api)
        runner=web.AppRunner(server);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1];journal=DeliveryJournal(fixture.root/'delivery.sqlite')
        try:
            with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'123456:SYNTHETIC_LOCAL_ONLY','API_SPORTS_KEY':'','ZEYNAL_HYBRID_NBA_RESEARCH':'0'}):
                main=importlib.import_module('main');engine=main.Faz23Engine
                with patch.object(main,'TELEGRAM_BOT_TOKEN','123456:SYNTHETIC_LOCAL_ONLY'),\
                    patch.object(main,'Application',SimpleNamespace(builder=lambda:Application.builder().token('123456:SYNTHETIC_LOCAL_ONLY')
                        .base_url(f'http://127.0.0.1:{port}/bot').request(AuditedRequest(journal)))),\
                    patch.object(main,'Faz23Engine',lambda:engine(str(fixture.root/'faz23.sqlite'))):app=main.build_app()
                replay=SimpleNamespace(cases=lambda:[],has_pair=lambda h,a:True,analyze=AsyncMock(return_value=dict(
                    status='ABSTAIN',html='SYNTHETIC_OLD_DATE_ARCHIVE_ONLY',new_record=False)))
                install_isolated_services(app,archive,root,chat_id=17,transport=fixture.fetch,
                    nba_service=fixture.service,nba_replay=replay)
                await app.initialize()
                try:
                    scheduler=app.bot_data['nba_overnight_scheduler'];scheduler.clock=lambda:fixture.now
                    app.bot_data['last_nba_overnight_poll']=await scheduler.tick()
                    self.assertEqual(sent,[]);self.assertEqual(scheduler.last_report['progress']['pending'],1)
                    before=fixture.service.ledger.path.read_bytes()
                    commands=['/start','/nba','/analyze','/test nba','/test research','/predictions NBA','/accuracy NBA','/compare NBA 401000123',
                              '/analyze NBA 2026-11-12 Synthetic Hawks vs Synthetic Bears']
                    with patch.object(fixture.service,'_predict',side_effect=AssertionError('NO REGENERATION')):
                        for i,command in enumerate(commands):
                            update=Update.de_json(dict(update_id=i+1,message=dict(message_id=i+1,date=fixture.now,
                                chat=dict(id=17,type='private'),**{'from':dict(id=23,is_bot=False,first_name='Synthetic human')},
                                text=command,entities=[dict(type='bot_command',offset=0,length=len(command.split()[0]))])),app.bot)
                            await app.process_update(update)
                    text='\n'.join(sent)
                    for expected in ('NBA otomatik PREMATCH: AÇIK','REGISTERED_PROTOCOL_VALID','Bekleyen 1',
                                     'KAYITLI NBA TAHMİNLERİ','KAYITLI MODEL KARŞILAŞTIRMASI','NOT_CALIBRATED'):
                        self.assertIn(expected,text)
                    self.assertNotIn('Analiz hizmeti kullanılamıyor',text)
                    self.assertNotIn('SYNTHETIC_OLD_DATE_ARCHIVE_ONLY',text)
                    replay.analyze.assert_awaited_once_with('NBA','2026-11-12','Synthetic Hawks','Synthetic Bears')
                    self.assertEqual(before,fixture.service.ledger.path.read_bytes())
                    self.assertTrue(all(len(v.encode('utf-16-le'))//2<=4096 for v in sent))
                finally:await app.shutdown()
        finally:await runner.cleanup()
