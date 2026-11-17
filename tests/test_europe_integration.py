"""Synthetic E/U sources and real preserved archive; not real Telegram E2E."""
import asyncio
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import unittest
from unittest.mock import AsyncMock,Mock,patch

from telegram.ext import ApplicationHandlerStop

from core.team_identity import digest
from hybrid_engine.europe_models import prepare,PreparedEurope,catalog,season_url
from hybrid_engine.europe_live import EuropeanService,EuropeanRegistry
from hybrid_engine.europe_reports import EuropeanReports,EuropeanReportRouter
from hybrid_engine.frozen_archive import FrozenArchive,FrozenHybridService
from hybrid_engine.prospective_results import ProspectiveResults
from hybrid_engine.predictions_command import PredictionsCommand,render_predictions
from tests.test_season_archive_audit import NOW,euro
from tests.test_team_identity import documents,clubs

ROOT=Path(__file__).resolve().parents[1]


def raw_games(competition='E'):
    result=[];directory={r['code']:r for r in clubs()}
    for pair,(h,a) in enumerate((('PRS','ULK'),('PAR','BAS'))):
        for i in range(21):
            n=pair*21+i+1;g=euro();g.update(identifier=f'{competition}2026_{n}',gameCode=n,played=i>0)
            g['season'].update(code=competition+'2026',competitionCode=competition)
            start=NOW+4*3600 if i==0 else NOW-i*86400-3600
            g['utcDate']=datetime.fromtimestamp(start,timezone.utc).isoformat()
            for side,team in (('local',h),('road',a)):
                g[side]['club']=deepcopy(directory[team])
                if not i:g[side].update(score=0,partials={**{f'partials{q}':0 for q in range(1,5)},'extraPeriods':{}})
                else:
                    values=[18+(i+q+(2 if side=='local' else 0))%8 for q in range(4)]
                    g[side].update(score=sum(values),partials={**{f'partials{q+1}':v for q,v in enumerate(values)},'extraPeriods':{}})
            if i and g['local']['score']==g['road']['score']:
                g['local']['score']+=1;g['local']['partials']['partials4']+=1
            result.append(g)
    return dict(data=result,total=len(result))


class Source:
    def __init__(self,league,clock=None):
        self.league=league;self.clock=clock or (lambda:NOW);self.raw=raw_games('E' if league=='EUROLEAGUE' else 'U')
        self.calls=[];self.offline=False
    def receipt(self,url,document):
        return dict(provider='EUROLEAGUE_LIVE',source_url=url,status='DOCUMENT_RECEIVED',http_status=200,
            document=deepcopy(document),document_sha256=digest(document),observed_at_utc=int(self.clock())-1,ingested_at_utc=int(self.clock()))
    def __call__(self,provider,url):
        self.calls.append(url)
        if self.offline:return dict(status='SOURCE_ACCESS_DENIED',http_status=403,provider=provider,source_url=url)
        if url==season_url(self.league,2026):return self.receipt(url,self.raw)
        for r in documents(self.league).values():
            if r['source_url']==url:return self.receipt(url,r['document'])
        raise AssertionError('Unexpected synthetic source URL')


class EuropeanPreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.timer=patch('time.time',return_value=NOW);self.timer.start();self.addCleanup(self.timer.stop)

    def test_distinct_league_models_train_from_own_native_source(self):
        models=[]
        for code in ('EUROLEAGUE','EUROCUP'):
            source=Source(code);r=prepare(self.root,code,2026,source('EUROLEAGUE_LIVE',season_url(code,2026)))
            m=PreparedEurope(self.root,code,2026);models.append(m)
            self.assertEqual(r['training_games'],40);self.assertEqual(m.league,code)
            self.assertEqual(m.model.identity[0],'EuroLeague' if code=='EUROLEAGUE' else 'EuroCup')
            self.assertEqual(m.receipt['source_url'],season_url(code,2026))
        self.assertNotEqual(models[0].sha256,models[1].sha256)

    def test_missing_model_and_insufficient_history_are_explicit(self):
        with self.assertRaisesRegex(ValueError,'OFFLINE_PREPARATION_REQUIRED'):PreparedEurope(self.root,'EUROCUP',2026)
        source=Source('EUROCUP');source.raw['data']=source.raw['data'][:10];source.raw['total']=10
        with self.assertRaisesRegex(ValueError,'INSUFFICIENT_HIERARCHICAL'):
            prepare(self.root,'EUROCUP',2026,source('EUROLEAGUE_LIVE',season_url('EUROCUP',2026)))
        self.assertFalse(list(self.root.glob('prepared-*')))

    def test_wrong_competition_future_clock_and_changed_document_are_rejected(self):
        source=Source('EUROLEAGUE');r=source('EUROLEAGUE_LIVE',season_url('EUROLEAGUE',2026))
        with self.assertRaisesRegex(ValueError,'SOURCE_BINDING'):catalog(r,'EUROCUP',2026)
        for key in ('clock','digest'):
            bad=deepcopy(r)
            if key=='clock':bad['ingested_at_utc']=NOW+1
            else:bad['document_sha256']='a'*64
            with self.subTest(key=key),self.assertRaises(ValueError):catalog(bad,'EUROLEAGUE',2026)

    def test_prepared_training_source_and_model_tamper_fail_closed(self):
        source=Source('EUROCUP');r=prepare(self.root,'EUROCUP',2026,source('EUROLEAGUE_LIVE',season_url('EUROCUP',2026)))
        path=Path(r['path']);w=json.loads(path.read_text());w['payload']['model']['coefficients'][0]+=1
        path.write_text(json.dumps(w))
        with self.assertRaisesRegex(ValueError,'MODEL_PIN'):PreparedEurope(self.root,'EUROCUP',2026)

    def test_model_age_is_not_silently_ignored(self):
        source=Source('EUROLEAGUE');prepare(self.root,'EUROLEAGUE',2026,source('EUROLEAGUE_LIVE',season_url('EUROLEAGUE',2026)))
        with patch('time.time',return_value=NOW+3*86400+1):
            with self.assertRaisesRegex(ValueError,'SCOPE_SOURCE_OR_AGE'):PreparedEurope(self.root,'EUROLEAGUE',2026)


class EuropeanServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.clock=NOW;self.timer=patch('time.time',side_effect=lambda:self.clock);self.timer.start();self.addCleanup(self.timer.stop)
        self.sources={};self.services={}
        for code in ('EUROLEAGUE','EUROCUP'):
            source=Source(code,lambda:self.clock);self.sources[code]=source
            prepare(self.root/'models',code,2026,source('EUROLEAGUE_LIVE',season_url(code,2026)))
            self.services[code]=EuropeanService(code,self.root/code,self.root/'models',source)

    async def analyze(self,code='EUROCUP',day='2026-11-11',home='Paris Basketball',away='Fenerbahce Beko'):
        return await self.services[code].analyze(code,day,home,away)

    async def test_both_leagues_create_real_samples_and_arithmetic_consistent_records_without_fit(self):
        for code in self.services:
            with patch('hybrid_engine.models.HierarchicalStrength.fit',side_effect=AssertionError('NO REQUEST TRAINING')):
                r=await self.analyze(code)
            self.assertEqual(r['status'],'EUROPE_HYBRID_OK',r);self.assertTrue(r['new_record'])
            p=self.services[code].registry.records()[0]['payload'];q=p['components']['BAYES_QMC']['prediction']
            self.assertEqual(p['components']['BAYES_QMC']['intervals']['scenarios'],10000)
            self.assertAlmostEqual(sum(v[0] for v in q['quarters']),q['home'])
            self.assertAlmostEqual(sum(v[1] for v in q['quarters']),q['away'])
            self.assertLess(p['prediction_generated_at_utc'],p['fixture']['start_ts_utc'])
            self.assertFalse(p['training_in_request']);self.assertIn('NOT_CALIBRATED',''.join(r['html_parts']))
            self.assertTrue(all(len(v.encode('utf-16-le'))//2<=3200 for v in r['html_parts']))

    async def test_alias_repeat_preserves_first_record_and_replays_without_resimulation(self):
        first=await self.analyze();paths={p.name:p.read_bytes() for p in (self.root/'EUROCUP').iterdir()}
        with patch('hybrid_engine.models.HierarchicalStrength.predict',side_effect=AssertionError('NO RESIMULATION')):
            second=await self.analyze(home='Paris',away='Fenerbahce')
        self.assertEqual(first['forecast_sha256'],second['forecast_sha256']);self.assertFalse(second['new_record'])
        self.assertEqual(paths,{p.name:p.read_bytes() for p in (self.root/'EUROCUP').iterdir()})

    async def test_started_match_cannot_create_new_prematch(self):
        self.clock=NOW+4*3600
        r=await self.analyze();self.assertEqual(r['status'],'ABSTAIN')
        self.assertFalse(self.services['EUROCUP'].registry.records())

    async def test_started_match_can_replay_an_existing_genuine_record(self):
        first=await self.analyze(home='Paris Basketball',away='Fenerbahce New Sponsor Istanbul');self.clock=NOW+5*3600
        with patch.object(self.sources['EUROCUP'],'__call__',side_effect=AssertionError('NO NETWORK')):
            r=await self.analyze(home='Paris Basketball',away='Fenerbahce New Sponsor Istanbul')
        self.assertEqual(r['forecast_sha256'],first['forecast_sha256']);self.assertFalse(r['new_record'])

    async def test_wrong_date_and_missing_history_do_not_become_predictions(self):
        r=await self.analyze(day='2026-11-12');self.assertEqual(r['status'],'ABSTAIN')
        self.assertFalse(self.services['EUROCUP'].registry.records())
        source=self.sources['EUROCUP'];source.raw['data']=[g for g in source.raw['data'] if not g['played']];source.raw['total']=len(source.raw['data'])
        r=await self.analyze();self.assertEqual(r['status'],'ABSTAIN');self.assertFalse(self.services['EUROCUP'].registry.records())

    async def test_source_outage_and_missing_prepared_artifact_leave_archive_untouched(self):
        self.sources['EUROCUP'].offline=True;r=await self.analyze();self.assertEqual(r['status'],'ABSTAIN')
        self.sources['EUROCUP'].offline=False;self.services['EUROCUP'].models=self.root/'missing-models'
        r=await self.analyze();self.assertEqual(r['status'],'ABSTAIN');self.assertIn('--prepare-europe',r['html'])
        self.assertFalse(self.services['EUROCUP'].registry.records())

    async def test_fixture_recheck_conflict_aborts_without_first_publication(self):
        s=self.sources['EUROCUP'];original=s.__call__;count=0
        def changed(provider,url):
            nonlocal count
            if url==season_url('EUROCUP',2026):
                count+=1
                if count==3:s.raw['data'][0]['utcDate']='2026-11-11T21:00:00Z'
            return original(provider,url)
        self.services['EUROCUP'].fetcher=changed
        self.services['EUROCUP'].preflight.fetcher=changed
        r=await self.analyze();self.assertEqual(r['status'],'ABSTAIN');self.assertFalse(self.services['EUROCUP'].registry.records())

    async def test_tipoff_during_simulation_cannot_publish_prematch(self):
        from hybrid_engine.models import HierarchicalStrength
        original=HierarchicalStrength.predict
        def advance(model,*args,**kwargs):
            forecast=original(model,*args,**kwargs)
            self.clock=NOW+4*3600
            return forecast
        with patch.object(HierarchicalStrength,'predict',advance):r=await self.analyze()
        self.assertEqual(r['status'],'ABSTAIN');self.assertIn('TIPOFF_DURING_SIMULATION',r['html'])
        self.assertEqual(self.services['EUROCUP'].registry.records(),[])

    async def test_appending_just_after_tipoff_cannot_be_prematch(self):
        from hybrid_engine.forward_validation import ForwardRegistry
        original=ForwardRegistry.record
        def advance(registry,payload):
            self.clock=NOW+4*3600
            return original(registry,payload)
        with patch.object(ForwardRegistry,'record',advance):r=await self.analyze()
        self.assertEqual(r['status'],'ABSTAIN');self.assertEqual(self.services['EUROCUP'].registry.records(),[])

    async def test_official_final_appends_without_changing_prediction_and_excludes_ot(self):
        await self.analyze();registry=self.services['EUROCUP'].registry
        old=registry.records()[0];raw=(registry.root/old['publication']['forecast']['file']).read_bytes()
        self.clock=NOW+5*3600;g=self.sources['EUROCUP'].raw['data'][0];g['played']=True
        for side,parts,ot in (('local',[20,20,20,20],8),('road',[20,20,20,20],12)):
            g[side].update(score=sum(parts)+ot,partials={**{f'partials{i+1}':v for i,v in enumerate(parts)},'extraPeriods':{'1':ot}})
        receipt=self.sources['EUROCUP']('EUROLEAGUE_LIVE',season_url('EUROCUP',2026))
        registry.settle(receipt,2026);out=registry.outcome(old['payload'])
        self.assertIsNotNone(out)
        rows=EuropeanReports(self.services['EUROCUP']).read('EUROCUP')['forecasts']
        self.assertTrue(all(r['actual']==[80,80] for r in rows));self.assertTrue(all(r['final_with_ot']==[88,92] for r in rows))
        self.assertEqual((registry.root/old['publication']['forecast']['file']).read_bytes(),raw)
        count=len(list(registry.root.glob('outcome-*')));registry.settle(receipt,2026)
        self.assertEqual(len(list(registry.root.glob('outcome-*'))),count)


class EuropeanListingTests(unittest.IsolatedAsyncioTestCase):
    async def test_preserved_five_matches_list_without_model_or_new_prediction(self):
        with TemporaryDirectory() as tmp:
            archive=FrozenArchive(ROOT/'docs/prospective/euroleague-20261112');before={p.name:p.read_bytes() for p in archive.path.iterdir()}
            results=ProspectiveResults(archive,Path(tmp)/'results')
            service=SimpleNamespace(league='EUROLEAGUE',registry=SimpleNamespace(independent_records=lambda:[]))
            reader=EuropeanReports(service,results);r=reader.read('EuroLeague')
            self.assertEqual(r['unique_fixtures'],5);self.assertEqual(len(r['forecasts']),20)
            text=''.join(render_predictions(r,league='EUROLEAGUE'))
            self.assertIn('KAYITLI EUROLEAGUE',text);self.assertIn('E2026_',text);self.assertIn('/compare EUROLEAGUE',text)
            self.assertIn('bilinmiyor',text);self.assertTrue(all(v['first_archived_at_utc'] is None for v in r['forecasts']))
            self.assertEqual(before,{p.name:p.read_bytes() for p in archive.path.iterdir()})
            command=PredictionsCommand(None,SimpleNamespace(append=Mock()),17,league_reports={'EUROLEAGUE':reader})
            reply=AsyncMock();u=SimpleNamespace(update_id=1,effective_chat=SimpleNamespace(id=17),effective_message=SimpleNamespace(reply_text=reply))
            with self.assertRaises(ApplicationHandlerStop):await command.handle(u,SimpleNamespace(args=['EuroLeague']))
            self.assertIn('KAYITLI EUROLEAGUE',''.join(c.args[0] for c in reply.call_args_list))

    async def test_europe_ids_cannot_be_rendered_as_nba_or_cross_competition(self):
        row=dict(fixture_id='f',provider_fixture_ids=['U2026_1'],fixture_start_utc=NOW+1000,model_digest='a',home='A',away='B',
            created_utc=NOW,prediction=[80.,79.],model_version='SYNTHETIC',actual=None,first_archived_at_utc=NOW)
        r=dict(status='VERIFIED_LIVE_REPORT',forecasts=[row],unique_fixtures=1,pending=1)
        self.assertIn('EUROCUP',''.join(render_predictions(r,league='EUROCUP')))
        for code in ('NBA','EUROLEAGUE'):
            with self.assertRaises(ValueError):render_predictions(r,league=code)

    async def test_router_preserves_original_nba_reader_and_renderers(self):
        prior=Mock();prior.read.return_value={'native':'nba'};prior.render_accuracy.return_value='NBA unchanged'
        euro=Mock();router=EuropeanReportRouter(prior,{'EUROLEAGUE':euro})
        r=router.read('NBA','401000123');self.assertEqual(router.render_accuracy(r),'NBA unchanged')
        prior.read.assert_called_once_with('NBA','401000123');euro.read.assert_not_called()

    async def test_replay_only_refuses_live_europe_configuration(self):
        from hybrid_engine.test_bot import install_isolated_services
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'REPLAY_ONLY_FORBIDS'):
                install_isolated_services(Mock(),Mock(),tmp,chat_id=17,replay_only=True,europe_directory=Path(tmp)/'europe')


class EuropeanTelegramDispatchTests(unittest.IsolatedAsyncioTestCase):
    """Real PTB routing against loopback HTTP, not external Telegram delivery."""
    async def test_all_three_leagues_and_preserved_archive_use_registered_handlers(self):
        import importlib
        import os
        from aiohttp import web
        from telegram import Update
        from telegram.ext import Application
        from telegram_delivery import DeliveryJournal
        from hybrid_engine.test_bot import install_isolated_services,AuditedRequest
        from tests.test_phase91 import ten_game_ledger
        archive=FrozenArchive(ROOT/'docs/prospective/euroleague-20261112')
        with TemporaryDirectory() as tmp,patch('time.time',return_value=NOW):
            root=Path(tmp);ledger,_=ten_game_ledger(root/'nba.sqlite',1);before=ledger.path.read_bytes();sent=[]
            sources={c:Source(c) for c in ('EUROLEAGUE','EUROCUP')}
            for code,source in sources.items():
                prepare(root/'europe/models',code,2026,source('EUROLEAGUE_LIVE',season_url(code,2026)))
            def fetch(provider,url):return sources['EUROCUP' if '/U/' in url else 'EUROLEAGUE'](provider,url)
            async def api(request):
                name=request.path.rsplit('/',1)[-1]
                if name=='getMe':result=dict(id=123456,is_bot=True,first_name='Synthetic',username='zeynal_test_bot')
                elif name=='sendMessage':
                    p=dict(await request.post());sent.append(p['text'])
                    result=dict(message_id=100+len(sent),date=NOW,chat=dict(id=17,type='private'),text=p['text'])
                else:result=True
                return web.json_response(dict(ok=True,result=result))
            server=web.Application();server.router.add_route('*','/{path:.*}',api)
            runner=web.AppRunner(server);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
            port=site._server.sockets[0].getsockname()[1];journal=DeliveryJournal(root/'delivery.sqlite')
            with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'123456:SYNTHETIC_LOCAL_ONLY','API_SPORTS_KEY':'','ZEYNAL_HYBRID_NBA_RESEARCH':'0'}):
                main=importlib.import_module('main');engine=main.Faz23Engine
                class Local:
                    @staticmethod
                    def builder():return Application.builder().base_url(f'http://127.0.0.1:{port}/bot').request(AuditedRequest(journal))
                with patch.object(main,'Application',Local),patch.object(main,'Faz23Engine',lambda:engine(str(root/'faz23.sqlite'))):app=main.build_app()
            install_isolated_services(app,archive,root/'isolated',chat_id=17,transport=fetch,
                nba_service=SimpleNamespace(ledger=ledger),europe_directory=root/'europe')
            await app.initialize()
            try:
                commands=['/predictions NBA','/accuracy NBA','/compare NBA 401000123','/predictions EuroLeague','/euroleague 2026-11-11','/eurocup 2026-11-11',
                    '/analyze EuroLeague 2026-11-11 Paris Basketball vs Fenerbahce Beko',
                    '/analyze EuroCup 2026-11-11 Paris Basketball vs Fenerbahce Beko',
                    '/predictions EuroCup','/accuracy EuroCup','/compare EuroCup U2026_1']
                for i,command in enumerate(commands):
                    u=Update.de_json(dict(update_id=i+1,message=dict(message_id=i+1,date=NOW,chat=dict(id=17,type='private'),
                        **{'from':dict(id=23,is_bot=False,first_name='Synthetic input')},text=command,
                        entities=[dict(type='bot_command',offset=0,length=len(command.split()[0]))])),app.bot)
                    await app.process_update(u)
                text='\n'.join(sent)
                for expected in ('KAYITLI NBA','MAE 7.00','Gerçek 115 – 109','Maç: 5 | Tahmin: 20','EUROLEAGUE HİBRİT ARAŞTIRMA',
                        'EUROCUP HİBRİT ARAŞTIRMA','KAYITLI EUROCUP','U2026_1','NOT_CALIBRATED','KAYITLI MODEL KARŞILAŞTIRMASI'):
                    self.assertIn(expected,text)
                self.assertEqual(before,ledger.path.read_bytes())
                self.assertTrue(all(len(s.encode('utf-16-le'))//2<=4096 for s in sent))
                for service in app.bot_data['europe_services'].values():self.assertEqual(len(service.registry.independent_records()),1)
                groups=[g for g,hs in app.handlers.items() for h in hs if 'predictions' in getattr(h,'commands',[])]
                self.assertEqual(groups,[-50])
            finally:await app.shutdown();await runner.cleanup()


class EuropeanNativeEvidenceTests(unittest.TestCase):
    def test_real_official_capture_has_two_distinct_prematch_archives_and_replays_without_inference(self):
        import tarfile
        import hashlib
        packet=ROOT/'docs/evidence/europe-phase95-native-20261117.tar.gz'
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            with tarfile.open(packet,'r:gz') as t:
                for item in t:
                    self.assertTrue(item.isfile());self.assertNotIn('..',Path(item.name).parts);self.assertFalse(Path(item.name).is_absolute())
                    p=root/item.name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(t.extractfile(item).read())
            capture=json.loads(next(root.glob('capture-*.json')).read_text());self.assertEqual(digest(capture['payload']),capture['sha256'])
            self.assertFalse(capture['payload']['actual_telegram_delivery_verified'])
            before={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*.json')}
            for row in capture['payload']['results']:
                code=row['league'];registry=EuropeanRegistry(root/code.lower(),code);records=registry.independent_records()
                self.assertEqual(len(records),1);p=records[0]['payload'];self.assertEqual(digest(p),row['snapshot_sha256'])
                self.assertTrue(records[0]['publication']['eligible_for_prospective_audit'])
                self.assertLess(records[0]['publication']['first_archived_at_utc'],p['fixture']['start_ts_utc'])
                self.assertFalse(row['repeat_new_record']);self.assertEqual(row['analysis_status'],'EUROPE_HYBRID_OK')
                for name,m in p['components'].items():
                    self.assertEqual(m['intervals']['scenarios'],10000)
                    self.assertAlmostEqual(sum(sum(v) for v in m['prediction']['quarters']),m['prediction']['total'])
                with patch('time.time',return_value=capture['payload']['captured_at_utc']):
                    model=PreparedEurope(root/'models',code,2026)
                self.assertEqual(model.sha256,p['version']);self.assertEqual(model.wrapper['payload']['training_games'],110 if code=='EUROLEAGUE' else 112)
                def offline(*args):raise AssertionError('ARCHIVE REPLAY MUST NOT DOWNLOAD')
                service=EuropeanService(code,root/code.lower(),root/'models',offline)
                with patch('hybrid_engine.models.HierarchicalStrength.predict',side_effect=AssertionError('NO NEW SIMULATION')):
                    r=asyncio.run(service.analyze(code,row['day'],row['home'],row['away']))
                self.assertFalse(r['new_record']);self.assertIn('ARŞİV REPLAY',''.join(r['html_parts']))
            self.assertEqual(before,{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*.json')})
