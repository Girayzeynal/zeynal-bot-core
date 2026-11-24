"""Real inference + synthetic fixture/Telegram transport; not external E2E."""
import asyncio
from copy import deepcopy
from datetime import datetime,timezone
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import time
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch,Mock,AsyncMock

from core.team_identity import digest
from hybrid_engine.europe_models import prepare,season_url
from hybrid_engine.europe_prematch import (AutomaticEuropeanService,SinglePrematchRegistry,
    EuropeanPrematchScheduler,candidates,safe_lead,status,LOOKAHEAD)
from hybrid_engine.europe_reports import EuropeanReports
from hybrid_engine.predictions_command import render_predictions
from tests.test_europe_integration import Source,ROOT
from tests.test_season_archive_audit import NOW

# 11 Nov 2026, 22:30 Istanbul; all histories remain earlier than preparation.
START=int(datetime(2026,11,11,19,30,tzinfo=timezone.utc).timestamp())


def publication_worker(directory,payload,at,output):
    """Forked publication only: no network, fitting or large simulation workers."""
    from time import sleep
    with patch('time.time',return_value=at):
        registry=SinglePrematchRegistry(directory,'EUROCUP')
        for _ in range(20):
            try:
                p,new=registry.record(payload);output.put((digest(p),new));return
            except ValueError as exc:
                if str(exc)!='EUROPE_PREMATCH_PUBLICATION_BUSY':raise
                sleep(.01)
        output.put(('BUSY',False))


class EuropeanAutomaticPrematchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.now=NOW;timer=patch('time.time',side_effect=lambda:self.now);timer.start();self.addCleanup(timer.stop)
        self.sources={};self.services={}
        for code in ('EUROLEAGUE','EUROCUP'):
            source=Source(code,lambda:self.now)
            for g in source.raw['data']:
                if not g['played']:g['utcDate']=datetime.fromtimestamp(START,timezone.utc).isoformat()
            self.sources[code]=source
            prepare(self.root/'models',code,2026,source('EUROLEAGUE_LIVE',season_url(code,2026)))
            self.services[code]=AutomaticEuropeanService(code,self.root/code,self.root/'models',source)
        self.now=START-105*60
        self.scheduler=EuropeanPrematchScheduler(self.services,self.root/'automatic',clock=lambda:self.now)

    async def analyze(self,code='EUROCUP',service=None):
        return await (service or self.services[code]).analyze(code,'2026-11-11','Paris Basketball','Fenerbahce Beko')

    def frozen_bytes(self,code='EUROCUP'):
        return {p.name:p.read_bytes() for p in self.services[code].registry.root.glob('*.json')}

    async def test_both_leagues_capture_real_samples_90_to_120_minutes_early_without_fitting(self):
        model_files={p.name:p.read_bytes() for p in (self.root/'models').iterdir()}
        with patch('hybrid_engine.models.HierarchicalStrength.fit',side_effect=AssertionError('NO ONLINE FIT')):
            r=await self.scheduler.tick()
        self.assertEqual(r['status'],'CHECKED')
        for code,s in self.services.items():
            self.assertEqual(len(s.registry.independent_records()),2)
            self.assertEqual(sum(v['new_record'] for v in r['leagues'][code]['results']),2)
            for item in s.registry.independent_records():
                p=item['payload'];self.assertEqual(item['publication']['classification'],'PREMATCH')
                self.assertGreater(START-item['publication']['first_archived_at_utc'],900)
                self.assertEqual(p['components']['BAYES_QMC']['intervals']['scenarios'],10000)
                self.assertFalse(p['training_in_request']);self.assertIsNone(p['confidence_index'])
        self.assertEqual(model_files,{p.name:p.read_bytes() for p in (self.root/'models').iterdir()})

    async def test_evening_captures_next_day_both_leagues_and_restart_replays_without_retiming(self):
        self.now=NOW;tomorrow=START+86400
        day=datetime.fromtimestamp(tomorrow,timezone.utc).date().isoformat()
        for source in self.sources.values():
            for g in source.raw['data']:
                if not g['played']:g['utcDate']=datetime.fromtimestamp(tomorrow,timezone.utc).isoformat()
        models={p.name:p.read_bytes() for p in (self.root/'models').iterdir()}
        with patch('hybrid_engine.models.HierarchicalStrength.fit',side_effect=AssertionError('NO ONLINE FIT')):
            report=await self.scheduler.tick()
        self.assertEqual(report['lookahead_seconds'],36*3600)
        self.assertEqual(report['status'],'CHECKED',report)
        originals={code:self.frozen_bytes(code) for code in self.services}
        for code,service in self.services.items():
            rows=report['leagues'][code]['results'];self.assertEqual(len(rows),2)
            self.assertTrue(all(r['new_record'] and r['day']==day and r['window']=='NEXT_36_HOURS' for r in rows))
            for item in service.registry.independent_records():
                p=item['payload'];self.assertEqual(p['prediction_generated_at_utc'],NOW)
                self.assertGreater(p['fixture']['start_ts_utc']-p['prediction_generated_at_utc'],24*3600)
                self.assertEqual(item['publication']['classification'],'PREMATCH')
                self.assertEqual(p['components']['BAYES_QMC']['intervals']['scenarios'],10000)
        self.now=tomorrow-14*60
        with patch('hybrid_engine.models.HierarchicalStrength.predict',side_effect=AssertionError('NO REGENERATION')):
            restarted={code:AutomaticEuropeanService(code,self.root/code,self.root/'models',self.sources[code]) for code in self.services}
            await EuropeanPrematchScheduler(restarted,self.root/'restart',clock=lambda:self.now).tick()
            for code,service in restarted.items():
                self.sources[code].offline=True
                before=len(self.sources[code].calls)
                replay=await service.analyze(code,day,'Paris Basketball','Fenerbahce Beko')
                self.assertEqual(replay['status'],'EUROPE_HYBRID_OK',replay)
                self.assertFalse(replay['new_record']);self.assertEqual(before,len(self.sources[code].calls))
                self.assertEqual(originals[code],self.frozen_bytes(code))
        self.assertEqual(models,{p.name:p.read_bytes() for p in (self.root/'models').iterdir()})

    async def test_36_hour_horizon_is_inclusive_and_later_fixtures_wait_for_their_window(self):
        for code,source in self.sources.items():
            games=[g for g in source.raw['data'] if not g['played']]
            for g,lead in zip(games,(LOOKAHEAD,LOOKAHEAD+1)):
                g['utcDate']=datetime.fromtimestamp(self.now+lead,timezone.utc).isoformat()
            scan=candidates(self.services[code],self.now)
            self.assertEqual(len(scan['selected']),1)
            self.assertEqual(scan['selected'][0]['fixture_start_utc'],self.now+LOOKAHEAD)
            self.assertEqual(scan['skipped']['OUTSIDE_EARLY_WINDOW'],1)
            self.assertEqual(self.services[code].registry.records(),[])
            self.now+=2
            scan=candidates(self.services[code],self.now)
            self.assertEqual(len(scan['selected']),2)

    async def test_2230_fixture_at_2210_can_capture_then_2216_and_2231_replay_exact_archive(self):
        self.now=START-20*60;r=await self.analyze();self.assertTrue(r['new_record'],r)
        before=self.frozen_bytes();pin=r['forecast_sha256'];self.sources['EUROCUP'].offline=True
        for at in (START-14*60,START+60):
            self.now=at
            with patch('hybrid_engine.models.HierarchicalStrength.predict',side_effect=AssertionError('NO REGENERATION')):
                replay=await self.analyze()
            self.assertFalse(replay['new_record']);self.assertEqual(replay['forecast_sha256'],pin)
            self.assertEqual(before,self.frozen_bytes())

    async def test_missing_early_record_at_2216_or_2231_abstains_instead_of_backfilling(self):
        for code,at in (('EUROCUP',START-4*60),('EUROLEAGUE',START+60)):
            self.now=at;r=await self.analyze(code)
            self.assertEqual(r['status'],'ABSTAIN');self.assertEqual(self.services[code].registry.records(),[])
            self.assertIn('WINDOW_CLOSED' if at<START else 'ALREADY_STARTED',r['html'])

    async def test_new_forecast_allowed_at_fourteen_minutes_with_pinned_model_untouched(self):
        """A T-14-minute native fixture must use the new adapter, not legacy T-15."""
        before={p.name:p.read_bytes() for p in (self.root/'models').iterdir()}
        self.now=START-14*60
        with patch('hybrid_engine.models.HierarchicalStrength.fit',
                   side_effect=AssertionError('NO_REQUEST_TIME_FIT')):
            for code in ('EUROCUP','EUROLEAGUE'):
                result=await self.analyze(code)
                self.assertEqual(result['status'],'EUROPE_HYBRID_OK',result)
                self.assertTrue(result['new_record'])
                self.assertGreater(START-result['timeline']['first_archived_at_utc'],300)
        self.assertEqual(before,{p.name:p.read_bytes() for p in (self.root/'models').iterdir()})

    async def test_exact_five_minute_boundary_abstains_with_no_archive(self):
        self.now=START-300
        for code in ('EUROCUP','EUROLEAGUE'):
            result=await self.analyze(code)
            self.assertEqual(result['status'],'ABSTAIN',result)
            self.assertIn('WINDOW_CLOSED',result['html'])
            self.assertEqual(self.services[code].registry.records(),[])

    async def test_scheduler_captures_2210_catchup_but_never_selects_last_5_minutes(self):
        self.now=START-20*60;r=await self.scheduler.tick()
        self.assertTrue(all(v['window']=='NEXT_36_HOURS' for g in r['leagues'].values() for v in g['results']))
        self.assertEqual(sum(len(g['results']) for g in r['leagues'].values()),4)
        self.now=START-4*60
        with patch('hybrid_engine.models.HierarchicalStrength.predict',side_effect=AssertionError('NO LATE CAPTURE')):
            await EuropeanPrematchScheduler(self.services,self.root/'restart',clock=lambda:self.now).tick()
        self.assertEqual(sum(len(s.registry.records()) for s in self.services.values()),4)

    async def test_restart_retry_and_updated_model_cannot_multiply_first_publication(self):
        first=await self.analyze();before=self.frozen_bytes()
        restarted=AutomaticEuropeanService('EUROCUP',self.root/'EUROCUP',self.root/'models',self.sources['EUROCUP'])
        r=await self.analyze(service=restarted);self.assertFalse(r['new_record']);self.assertEqual(first['forecast_sha256'],r['forecast_sha256'])
        original=restarted.registry.records()[0]['payload'];other=deepcopy(original);other['version']='SYNTHETIC_OTHER_VERSION'
        p,new=restarted.registry.record(other);self.assertFalse(new);self.assertEqual(p,original)
        self.assertEqual(before,self.frozen_bytes())

    async def test_concurrent_manual_and_scheduler_service_instances_share_one_publication(self):
        service=AutomaticEuropeanService('EUROCUP',self.root/'EUROCUP',self.root/'models',self.sources['EUROCUP'])
        a,b=await asyncio.gather(self.analyze(),self.analyze(service=service))
        self.assertEqual(a['status'],'EUROPE_HYBRID_OK',a);self.assertEqual(b['status'],'EUROPE_HYBRID_OK',b)
        self.assertEqual(sum((a['new_record'],b['new_record'])),1)
        self.assertEqual(a['forecast_sha256'],b['forecast_sha256']);self.assertEqual(len(service.registry.records()),1)

    async def test_process_publication_race_has_one_immutable_first_record(self):
        await self.analyze();p=self.services['EUROCUP'].registry.records()[0]['payload'];directory=self.root/'process-race';directory.mkdir()
        for ref in p['assets']:shutil.copy2(self.root/'EUROCUP'/ref['file'],directory/ref['file'])
        # Fork only after this test's inference thread pool has stopped. Child
        # publication uses no NumPy computation or async executor.
        await asyncio.get_running_loop().shutdown_default_executor()
        ctx=multiprocessing.get_context('fork');queue=ctx.Queue()
        processes=[ctx.Process(target=publication_worker,args=(str(directory),p,self.now,queue)) for _ in range(2)]
        try:
            for process in processes:process.start()
            for process in processes:
                deadline=time.monotonic()+15
                while process.exitcode is None and time.monotonic()<deadline:await asyncio.sleep(.01)
                process.join(0);self.assertEqual(process.exitcode,0)
            results=[queue.get(timeout=2) for _ in processes]
            self.assertEqual(sum(v[1] for v in results),1);self.assertEqual(len({v[0] for v in results}),1)
            self.assertEqual(len(SinglePrematchRegistry(directory,'EUROCUP').records()),1)
        finally:
            for process in processes:
                if process.is_alive():process.terminate();process.join(2)
            queue.close();queue.join_thread()

    async def test_rescheduled_provider_id_does_not_create_a_second_prediction(self):
        await self.analyze();service=self.services['EUROCUP'];p=service.registry.records()[0]['payload'];before=self.frozen_bytes()
        changed=deepcopy(p);changed['fixture']['canonical_id']='SYNTHETIC_RESCHEDULED_CANONICAL_ID'
        changed['fixture']['start_ts_utc']+=86400
        restored,new=service.registry.record(changed);self.assertFalse(new);self.assertEqual(restored,p)
        self.assertEqual(before,self.frozen_bytes())

    async def test_missing_prepared_models_and_missing_history_are_explicit_abstentions(self):
        for s in self.services.values():s.models=self.root/'no-models'
        r=await self.scheduler.tick();self.assertEqual(r['status'],'PARTIAL_ABSTAIN')
        self.assertTrue(all(v['reason']=='EUROPE_OFFLINE_PREPARATION_REQUIRED' for g in r['leagues'].values() for v in g['results']))
        self.assertTrue(all(not s.registry.records() for s in self.services.values()))
        for code,s in self.services.items():
            s.models=self.root/'models';raw=self.sources[code].raw
            raw['data']=[g for g in raw['data'] if not g['played']];raw['total']=len(raw['data'])
        self.now+=301
        r=await self.scheduler.tick(force=True)
        self.assertEqual(sum(len(g['results']) for g in r['leagues'].values()),4)
        self.assertTrue(all(v['reason']=='INSUFFICIENT_VERIFIED_HISTORY' for g in r['leagues'].values() for v in g['results']))

    async def test_official_failure_has_backoff_then_recovers_without_synthesized_predictions(self):
        for source in self.sources.values():source.offline=True
        r=await self.scheduler.tick();self.assertEqual(r['status'],'PARTIAL_ABSTAIN')
        calls=sum(len(s.calls) for s in self.sources.values());await self.scheduler.tick()
        self.assertEqual(calls,sum(len(s.calls) for s in self.sources.values()))
        self.now+=301
        for source in self.sources.values():source.offline=False
        r=await self.scheduler.tick();self.assertEqual(r['status'],'CHECKED')
        self.assertEqual(sum(len(s.registry.records()) for s in self.services.values()),4)

    async def test_boundary_crossed_during_simulation_cannot_publish(self):
        self.now=START-20*60
        from hybrid_engine.models import HierarchicalStrength
        original=HierarchicalStrength.predict
        def crossing(model,*args,**kwargs):
            result=original(model,*args,**kwargs);self.now=START-4*60;return result
        with patch.object(HierarchicalStrength,'predict',crossing):r=await self.analyze()
        self.assertEqual(r['status'],'ABSTAIN');self.assertEqual(self.services['EUROCUP'].registry.records(),[])

    async def test_boundary_crossed_while_writing_unpublished_asset_has_no_first_record(self):
        await self.analyze();payload=self.services['EUROCUP'].registry.records()[0]['payload'];root=self.root/'slow-disk';root.mkdir()
        for ref in payload['assets']:shutil.copy2(self.root/'EUROCUP'/ref['file'],root/ref['file'])
        registry=SinglePrematchRegistry(root,'EUROCUP')
        from hybrid_engine.forward_validation import ForwardRegistry
        original=ForwardRegistry.asset
        def slow(owner,prefix,p):
            result=original(owner,prefix,p)
            if prefix=='forecast':self.now=START-4*60
            return result
        with patch.object(ForwardRegistry,'asset',slow),self.assertRaisesRegex(ValueError,'WINDOW_CLOSED'):
            registry.record(payload)
        self.assertEqual(registry.records(),[]);self.assertEqual(list(root.glob('first-*')),[])

    async def test_source_live_score_despite_future_clock_is_not_prematch(self):
        for code,source in self.sources.items():
            source.raw['data'][0]['local']['score']=2
            with self.assertRaisesRegex(ValueError,'LIVE_SCORE'):candidates(self.services[code],self.now)
            r=await self.analyze(code);self.assertEqual(r['status'],'ABSTAIN');self.assertFalse(self.services[code].registry.records())

    async def test_journal_is_read_only_inspectable_and_hash_tamper_is_refused(self):
        await self.scheduler.tick();before={p.name:p.read_bytes() for p in (self.root/'automatic').iterdir()}
        r=status(self.root/'automatic');self.assertEqual(r['status'],'RECORDED_ATTEMPT_AVAILABLE')
        self.assertFalse(r['actual_telegram_delivery_verified']);self.assertFalse(r['forecast_created'])
        self.assertEqual(before,{p.name:p.read_bytes() for p in (self.root/'automatic').iterdir()})
        f=next((self.root/'automatic').glob('auto-*.json'));w=json.loads(f.read_text());w['payload']['maximum']=8;f.write_text(json.dumps(w))
        with self.assertRaisesRegex(ValueError,'JOURNAL_PIN'):status(self.root/'automatic')

    async def test_disk_error_is_visible_and_never_replaces_an_existing_archive(self):
        r=await self.analyze();before=self.frozen_bytes()
        with patch.object(self.scheduler,'publish',side_effect=OSError('SYNTHETIC_PRIVATE_DISK_DETAIL')):
            report=await self.scheduler.tick()
        self.assertEqual(report['journal_status'],'ABSTAIN_JOURNAL_UNAVAILABLE')
        self.assertNotIn('SYNTHETIC_PRIVATE_DISK_DETAIL',json.dumps(report))
        replay=await self.analyze();self.assertEqual(replay['forecast_sha256'],r['forecast_sha256'])
        for name,raw in before.items():self.assertEqual((self.root/'EUROCUP'/name).read_bytes(),raw)

    async def test_listing_comparison_accuracy_and_appended_final_preserve_original_prediction(self):
        await self.analyze();service=self.services['EUROCUP'];before=self.frozen_bytes();reader=EuropeanReports(service)
        r=reader.read('EUROCUP');self.assertEqual(r['unique_fixtures'],1);self.assertEqual(len(r['forecasts']),3)
        self.assertIn('/compare EUROCUP U2026_1',''.join(render_predictions(r,league='EUROCUP')))
        comparison=reader.render_compare(reader.read('EUROCUP','U2026_1'))
        for model in ('BAYES_QMC','BAYES_MC','FAZ13_REFERENCE'):self.assertIn(model,comparison)
        self.now=START+7200;g=self.sources['EUROCUP'].raw['data'][0];g['played']=True
        for side,parts in (('local',[20,21,22,23]),('road',[19,20,21,22])):
            g[side].update(score=sum(parts),partials={**{'partials'+str(i+1):v for i,v in enumerate(parts)},'extraPeriods':{}})
        service.collect_results();r=reader.read('EUROCUP','U2026_1')
        self.assertTrue(all(row['actual']==[86,82] for row in r['forecasts']))
        self.assertIn('Gerçek 86',reader.render_compare(r));self.assertIn('MAE',reader.render_accuracy(r))
        for name,raw in before.items():self.assertEqual((self.root/'EUROCUP'/name).read_bytes(),raw)

    async def test_scheduler_bound_rotation_and_loop_cancellation(self):
        scheduler=EuropeanPrematchScheduler(self.services,self.root/'bounded',clock=lambda:self.now,maximum=1)
        first=await scheduler.tick(force=True);second=await scheduler.tick(force=True)
        self.assertEqual([len(g['results']) for g in first['leagues'].values()],[1,0])
        self.assertEqual([len(g['results']) for g in second['leagues'].values()],[1,0])
        self.assertNotEqual(next(iter(first['leagues'])),next(iter(second['leagues'])))
        app=SimpleNamespace(bot_data={});task=asyncio.create_task(scheduler.run(app))
        for _ in range(100):
            if 'last_europe_prematch_poll' in app.bot_data:break
            await asyncio.sleep(.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertIn('last_europe_prematch_poll',app.bot_data)

    async def test_one_blocked_fixture_does_not_starve_other_eligible_matches(self):
        service=self.services['EUROCUP'];first=candidates(service,self.now)['selected'][0]
        original=service.analyze
        async def partial(league,day,home,away):
            if (home,away)==(first['home'],first['away']):
                return dict(status='ABSTAIN',reason='SYNTHETIC_UNAVAILABLE_PLAYER_INPUT')
            return await original(league,day,home,away)
        scheduler=EuropeanPrematchScheduler({'EUROCUP':service},self.root/'partial',clock=lambda:self.now,maximum=1)
        with patch.object(service,'analyze',partial):
            a=await scheduler.tick(force=True);b=await scheduler.tick(force=True)
        self.assertEqual(a['leagues']['EUROCUP']['results'][0]['status'],'ABSTAIN')
        self.assertEqual(b['leagues']['EUROCUP']['retry_deferred'],1)
        self.assertTrue(b['leagues']['EUROCUP']['results'][0]['new_record'])
        self.assertEqual(len(service.registry.records()),1)

class LegacyAsyncTimeoutHandlingTests(unittest.IsolatedAsyncioTestCase):
    """Python 3.10 can expose a distinct asyncio.TimeoutError class."""

    async def test_inference_timeout_is_per_fixture_abstain_and_retries(self):
        class LegacyAsyncTimeout(Exception):
            pass
        now=1795490000
        target=dict(fixture_id='fixture-1',fixture_start_utc=now+3600,
            provider_fixture_ids=['E2026_137'],day='2026-11-24',
            home='Dubai Basketball',away='Partizan Mozzart Bet Belgrade',
            window='NEXT_36_HOURS')
        scan=dict(selected=[target],skipped={},source_sha256='a'*64,
                  next_scan_utc=now+300)
        service=SimpleNamespace(analyze=AsyncMock(side_effect=LegacyAsyncTimeout('EXPIRED')))
        with TemporaryDirectory() as directory:
            scheduler=EuropeanPrematchScheduler({'EUROLEAGUE':service},
                Path(directory),clock=lambda:now)
            with patch('hybrid_engine.europe_prematch.candidates',return_value=scan),\
                 patch('hybrid_engine.europe_prematch.asyncio.TimeoutError',LegacyAsyncTimeout):
                report=await scheduler.tick(force=True)
            self.assertEqual(report['status'],'PARTIAL_ABSTAIN')
            row=report['leagues']['EUROLEAGUE']['results'][0]
            self.assertEqual(row['reason'],'EUROPE_AUTO_INFERENCE_OR_TIMEOUT')
            self.assertEqual(row['status'],'ABSTAIN')
            self.assertFalse(row['new_record'])
            self.assertEqual(scheduler.retry_after[('EUROLEAGUE','fixture-1')],now+300)
            service.analyze.assert_awaited_once()

    async def test_fixture_preflight_timeout_is_scoped_to_league(self):
        class LegacyAsyncTimeout(Exception):
            pass
        now=1795490000
        service=SimpleNamespace(analyze=AsyncMock())
        with TemporaryDirectory() as directory:
            scheduler=EuropeanPrematchScheduler({'EUROLEAGUE':service},
                Path(directory),clock=lambda:now)
            with patch('hybrid_engine.europe_prematch.candidates',
                       side_effect=LegacyAsyncTimeout('EXPIRED')),\
                 patch('hybrid_engine.europe_prematch.asyncio.TimeoutError',LegacyAsyncTimeout):
                report=await scheduler.tick(force=True)
            self.assertEqual(report['status'],'PARTIAL_ABSTAIN')
            self.assertEqual(report['leagues']['EUROLEAGUE']['reason'],
                             'OFFICIAL_FIXTURE_MODEL_OR_ARCHIVE_UNAVAILABLE')
            self.assertEqual(scheduler.next_scan['EUROLEAGUE'],now+300)
            service.analyze.assert_not_awaited()


class EuropeanPrematchBoundaryTests(unittest.TestCase):
    def test_exact_5_minute_boundary_and_invalid_generation_clocks(self):
        with patch('time.time',return_value=START-300):
            for generated in (START-400,START-300,START-299,True):
                with self.subTest(generated=generated),self.assertRaises(ValueError):
                    safe_lead(dict(fixture=dict(start_ts_utc=START),prediction_generated_at_utc=generated))
        with patch('time.time',return_value=START-301):safe_lead(dict(fixture=dict(start_ts_utc=START),prediction_generated_at_utc=START-302))

    def test_nba_and_unbounded_scheduler_parameters_refused(self):
        with TemporaryDirectory() as root:
            for maximum in (0,9,True):
                with self.assertRaises(ValueError):EuropeanPrematchScheduler({},root,maximum=maximum)
            with self.assertRaises(ValueError):EuropeanPrematchScheduler({'NBA':Mock()},root)


class EuropeanAutomaticTelegramTests(unittest.IsolatedAsyncioTestCase):
    async def test_registered_handlers_replay_automatic_archives_at_2210_2216_2231(self):
        import importlib
        from aiohttp import web
        from telegram import Update
        from telegram.ext import Application
        from telegram_delivery import DeliveryJournal
        from hybrid_engine.frozen_archive import FrozenArchive
        from hybrid_engine.nba_replay import NBAReplayArchive
        from hybrid_engine.test_bot import install_isolated_services,AuditedRequest
        archive=FrozenArchive(ROOT/'docs/prospective/euroleague-20261112');nba_replay=NBAReplayArchive()
        now=[NOW];sent=[]
        with TemporaryDirectory() as tmp,patch('time.time',side_effect=lambda:now[0]):
            root=Path(tmp);sources={code:Source(code,lambda:now[0]) for code in ('EUROLEAGUE','EUROCUP')}
            for code,source in sources.items():
                for g in source.raw['data']:
                    if not g['played']:g['utcDate']=datetime.fromtimestamp(START,timezone.utc).isoformat()
                prepare(root/'europe/models',code,2026,source('EUROLEAGUE_LIVE',season_url(code,2026)))
            def fetch(provider,url):return sources['EUROCUP' if '/U/' in url else 'EUROLEAGUE'](provider,url)
            async def api(request):
                method=request.path.rsplit('/',1)[-1]
                if method=='getMe':result=dict(id=123456,is_bot=True,first_name='Synthetic',username='zeynal_test_bot')
                elif method=='sendMessage':
                    p=dict(await request.post());sent.append(p['text'])
                    result=dict(message_id=100+len(sent),date=now[0],chat=dict(id=17,type='private'),text=p['text'])
                else:result=True
                return web.json_response(dict(ok=True,result=result))
            server=web.Application();server.router.add_route('*','/{path:.*}',api)
            runner=web.AppRunner(server);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
            port=site._server.sockets[0].getsockname()[1];journal=DeliveryJournal(root/'delivery.sqlite')
            try:
                with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'123456:SYNTHETIC_LOCAL_ONLY','API_SPORTS_KEY':'','ZEYNAL_HYBRID_NBA_RESEARCH':'0'}):
                    main=importlib.import_module('main');engine=main.Faz23Engine
                    with patch.object(main,'TELEGRAM_BOT_TOKEN','123456:SYNTHETIC_LOCAL_ONLY'),\
                        patch.object(main,'Application',SimpleNamespace(builder=lambda:Application.builder().token('123456:SYNTHETIC_LOCAL_ONLY')
                        .base_url(f'http://127.0.0.1:{port}/bot').request(AuditedRequest(journal)))),\
                        patch.object(main,'Faz23Engine',lambda:engine(str(root/'faz23.sqlite'))):app=main.build_app()
                    install_isolated_services(app,archive,root/'isolated',
                        chat_id=17,transport=fetch,europe_directory=root/'europe',nba_replay=nba_replay)
                    await app.initialize()
                    try:
                        now[0]=NOW  # 19:00 Istanbul; do not wait for the old two-hour window.
                        scheduler=app.bot_data['europe_prematch_scheduler'];scheduler.clock=lambda:now[0]
                        app.bot_data['last_europe_prematch_poll']=await scheduler.tick()
                        self.assertEqual(sum(len(s.registry.records()) for s in app.bot_data['europe_services'].values()),4)
                        before={str(p.relative_to(root)):p.read_bytes() for p in (root/'europe').rglob('*.json')}
                        commands=[]
                        for at in (START-20*60,START-14*60,START+60):
                            now[0]=at
                            for league in ('EUROLEAGUE','EUROCUP'):
                                commands.append((at,f'/analyze {league} 2026-11-11 Paris Basketball vs Fenerbahce Beko'))
                        commands += [(START+60,c) for c in ('/predictions EuroLeague','/predictions EuroCup',
                            '/compare EUROLEAGUE E2026_1','/compare EUROCUP U2026_1','/accuracy EUROLEAGUE','/accuracy EUROCUP','/test euroleague','/test eurocup',
                            '/test research','/research EUROCUP U2026_1')]
                        with patch('hybrid_engine.models.HierarchicalStrength.predict',side_effect=AssertionError('REPLAY ONLY')):
                            for i,(at,command) in enumerate(commands):
                                now[0]=at
                                update=Update.de_json(dict(update_id=i+1,message=dict(message_id=i+1,date=at,
                                    chat=dict(id=17,type='private'),**{'from':dict(id=23,is_bot=False,first_name='Synthetic human')},
                                    text=command,entities=[dict(type='bot_command',offset=0,length=len(command.split()[0]))])),app.bot)
                                await app.process_update(update)
                        text='\n'.join(sent)
                        self.assertEqual(sum('ZEYNAL | EUROLEAGUE ANALİZ' in p for p in sent),3)
                        self.assertEqual(sum('ZEYNAL | EUROCUP ANALİZ' in p for p in sent),3)
                        for expected in ('KAYITLI EUROLEAGUE','KAYITLI EUROCUP','KAYITLI MODEL KARŞILAŞTIRMASI',
                                         'DOĞRULANMIŞ CANLI PERFORMANS','Avrupa otomatik PREMATCH: AÇIK · gelecek 36 saat','NOT_CALIBRATED',
                                         'AYRI ADAY MODEL ARAŞTIRMASI','Bu maç için ayrı V2 kaydı yok'):
                            self.assertIn(expected,text)
                        self.assertNotIn('Analiz durduruldu',text);self.assertNotIn('hizmeti kullanılamıyor',text)
                        self.assertEqual(before,{str(p.relative_to(root)):p.read_bytes() for p in (root/'europe').rglob('*.json')})
                        self.assertTrue(all(len(p.encode('utf-16-le'))//2<=4096 for p in sent))
                    finally:await app.shutdown()
            finally:await runner.cleanup()
