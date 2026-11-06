"""Offline development integration; mocked replies, no Telegram connections."""
import asyncio
from copy import deepcopy
from datetime import datetime,timezone
import sys
import types
from unittest import IsolatedAsyncioTestCase,TestCase
from unittest.mock import AsyncMock,patch

from telegram.ext import CommandHandler
from prediction_inputs import digest
from faz41_evidence import REGISTRY
from faz42_schedule import seal_schedule
from faz43_development import DevelopmentAnalysisService,parse_request,render_analysis,register_development_analyze
from tests.test_faz42_history import NOW,history,permitted_registry
from tests.test_faz42_prospective import test_model as synthetic_model
from tests.test_faz33 import event

DAY='2026-11-06';START=NOW+3600;URL='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20261106'


class FakeApplication:
    def __init__(self,scope='DEVELOPMENT',running=False):self.bot_data={'deployment_scope':scope};self.running=running;self.handlers={0:[]}
    def add_handler(self,h):self.handlers[0].append(h)


class DevelopmentWorkflowTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.timer=patch('time.time',return_value=NOW);self.timer.start();self.addCleanup(self.timer.stop)
        self.current=NOW;self.registry=permitted_registry();self.pin=digest(self.registry);self.schedule=self.seal()
        self.inputs=dict(schedules=[self.schedule],history=history(self.registry),model=synthetic_model())
        self.backend=types.SimpleNamespace(load_inputs=AsyncMock(return_value=self.inputs))
        self.service=DevelopmentAnalysisService(self.backend,allow_synthetic=True,registry=self.registry,registry_pin=self.pin,clock=lambda:self.current)

    def seal(self,events=None,registry=None):
        registry=registry or self.registry;events=events or [event(START,'900000099')]
        for e in events:
            for row in e['competitions'][0]['competitors']:
                row['team']['displayName']='Home <unsafe>' if row['homeAway']=='home' else 'Away & team'
        with patch('time.time',return_value=NOW-50):return seal_schedule(dict(events=events),provider='ESPN',league='NBA',season_end_year=2027,
            source_url=URL,observed_at_utc=NOW-60,ingested_at_utc=NOW-55,usage='SYNTHETIC_TEST',registry=registry,registry_pin=digest(registry))

    async def analyze(self,text=None):return await self.service.analyze(text or '/analyze NBA '+DAY+' 19 vs 2')

    async def test_full_development_projection_has_periods_seed_proof_and_synthetic_label(self):
        r=await self.analyze();self.assertEqual(r['status'],'PREDICTED_EXPERIMENTAL');text=render_analysis(r)
        for item in ('1Q','2Q','3Q','4Q','1H','2H','NORMAL','SENTETİK TEST','Monte Carlo: 10000','Kalibrasyon: yapılmadı','Kaynak digest'):
            self.assertIn(item,text)
        self.assertEqual(r['prospective_records_created'],0);self.assertLess(len(text),3800)

    async def test_exact_names_are_source_resolved_and_html_is_escaped(self):
        r=await self.analyze('/analyze NBA '+DAY+' Home <unsafe> vs Away & team')
        self.assertEqual(r['status'],'PREDICTED_EXPERIMENTAL');text=render_analysis(r)
        self.assertIn('Home &lt;unsafe&gt;',text);self.assertIn('Away &amp; team',text);self.assertNotIn('<unsafe>',text)

    async def test_cached_prediction_is_not_regenerated_or_mutated_by_caller(self):
        r=await self.analyze();sha=r['snapshot']['sha256'];r['snapshot']['payload']['prediction']['total']=9999
        again=await self.analyze();self.assertEqual(again['snapshot']['sha256'],sha)
        self.assertNotEqual(again['snapshot']['payload']['prediction']['total'],9999)
        self.backend.load_inputs.assert_awaited_once()

    async def test_same_game_name_alias_returns_original_prediction(self):
        first=await self.analyze();second=await self.analyze('/analyze NBA '+DAY+' Home <unsafe> vs Away & team')
        self.assertEqual(first['snapshot']['sha256'],second['snapshot']['sha256']);self.assertEqual(len(self.service.cache),1)

    async def test_past_and_unsupported_league_do_not_fetch_inputs(self):
        for text in ['/analyze NBA 2026-11-05 19 vs 2','/analyze CBA '+DAY+' 19 vs 2']:
            self.assertEqual((await self.analyze(text))['status'],'ABSTAIN')
        self.backend.load_inputs.assert_not_awaited()

    async def test_invalid_request_does_not_fetch_inputs(self):
        for text in ['/analyze NBA bad 19 vs 2','/analyze NBA '+DAY+' Home vs Away vs Other','/analyze NBA '+DAY+' Same vs Same']:
            self.assertEqual((await self.analyze(text))['status'],'ABSTAIN')
        self.backend.load_inputs.assert_not_awaited()

    async def test_default_synthetic_refusal_and_unconfigured_backend_are_explicit(self):
        service=DevelopmentAnalysisService(self.backend,registry=self.registry,registry_pin=self.pin)
        self.assertEqual((await service.analyze('/analyze NBA '+DAY+' 19 vs 2'))['reason'],'SYNTHETIC_SOURCE_REFUSED')
        service=DevelopmentAnalysisService()
        self.assertEqual((await service.analyze('/analyze NBA '+DAY+' 19 vs 2'))['reason'],'DEVELOPMENT_SOURCE_NOT_CONFIGURED')

    async def test_unknown_usage_never_calls_projection_or_invents_a_score(self):
        registry=deepcopy(REGISTRY);self.inputs['schedules']=[self.seal(registry=registry)]
        service=DevelopmentAnalysisService(self.backend,allow_synthetic=True,registry=registry,registry_pin=digest(registry))
        with patch('faz42_snapshot.forecast') as model:
            r=await service.analyze('/analyze NBA '+DAY+' 19 vs 2')
        self.assertEqual(r['reason'],'SCHEDULE_USAGE_NOT_ESTABLISHED');model.assert_not_called()
        self.assertNotIn('1Q',render_analysis(r));self.assertEqual(len(service.cache),0)

    async def test_backend_timeout_and_exception_do_not_leak_tokens(self):
        self.backend.load_inputs.side_effect=RuntimeError('https://api.telegram.org/botSECRET/getMe')
        r=await self.analyze();self.assertEqual(r['reason'],'SOURCE_UNAVAILABLE');self.assertNotIn('SECRET',render_analysis(r))
        self.backend.load_inputs.side_effect=asyncio.TimeoutError()
        self.assertEqual((await self.analyze())['reason'],'SOURCE_TIMEOUT')

    async def test_ambiguous_fixture_is_not_guessed(self):
        self.inputs['schedules']=[self.seal([event(START,'900000099'),event(START+3600,'900000100')])]
        r=await self.analyze();self.assertEqual(r['reason'],'AMBIGUOUS_FIXTURE_MATCH');self.assertEqual(len(self.service.cache),0)

    async def test_unknown_or_fuzzy_team_name_is_not_guessed(self):
        r=await self.analyze('/analyze NBA '+DAY+' Hom vs Away')
        self.assertEqual(r['reason'],'NO_VERIFIED_FIXTURE_MATCH')

    async def test_turkey_calendar_date_is_used_in_fixture_resolution(self):
        late=int(datetime(2026,11,6,22,30,tzinfo=timezone.utc).timestamp());self.inputs['schedules']=[self.seal([event(late,'900000101')])]
        self.assertEqual((await self.analyze())['reason'],'NO_VERIFIED_FIXTURE_MATCH')
        self.assertEqual((await self.analyze('/analyze NBA 2026-11-07 19 vs 2'))['status'],'PREDICTED_EXPERIMENTAL')

    async def test_delivery_after_tipoff_and_old_cutoff_is_abstain_without_regeneration(self):
        await self.analyze();self.current=NOW+61
        self.assertEqual((await self.analyze())['reason'],'SNAPSHOT_STALE_NO_REGENERATION')
        self.current=START+1;self.assertEqual((await self.analyze())['reason'],'ALREADY_STARTED')
        self.backend.load_inputs.assert_awaited_once()

    async def test_cross_league_source_and_corrupt_snapshot_are_refused(self):
        r=await self.analyze('/analyze EUROLEAGUE '+DAY+' 19 vs 2');self.assertEqual(r['reason'],'CROSS_LEAGUE_SCHEDULE')
        r=await self.analyze();r['snapshot']['payload']['prediction']['total']=999
        self.assertEqual(self.service.for_delivery(r)['status'],'ABSTAIN')

    async def test_manual_day_plan_is_deduplicated_and_does_not_install_scheduler(self):
        async def load(league,day):
            return self.inputs if league=='NBA' else dict(schedules=[],history=[],model=synthetic_model())
        self.backend.load_inputs.side_effect=load;self.inputs['schedules']=[self.schedule,self.schedule]
        r=await self.service.prepare_day(DAY);self.assertEqual(r['unique_fixture_plans'],1)
        self.assertEqual(r['prospective_records_created'],0);self.assertEqual(r['scheduler_status'],'NOT_INSTALLED')
        again=await self.service.prepare_day(DAY)
        self.assertEqual(r['plans'][0]['snapshot']['sha256'],again['plans'][0]['snapshot']['sha256'])

    async def test_day_plan_without_backend_or_past_date_does_not_fetch(self):
        self.assertEqual((await self.service.prepare_day('bad'))['status'],'ABSTAIN')
        self.assertEqual((await self.service.prepare_day('2026-11-05'))['status'],'ABSTAIN')
        self.backend.load_inputs.assert_not_awaited()

    async def test_registered_handler_calls_only_allowed_stopped_development_application(self):
        app=FakeApplication();handler=register_development_analyze(app,self.service,allowed_chat_ids={123})
        message=types.SimpleNamespace(text='/analyze NBA '+DAY+' 19 vs 2',reply_text=AsyncMock())
        update=types.SimpleNamespace(effective_chat=types.SimpleNamespace(id=123),effective_message=message)
        context=types.SimpleNamespace(application=app);await handler.callback(update,context)
        message.reply_text.assert_awaited_once();self.assertEqual(message.reply_text.await_args.kwargs['parse_mode'],'HTML')
        self.assertIn('SENTETİK TEST',message.reply_text.await_args.args[0])

    async def test_unauthorized_chat_and_changed_runtime_scope_never_reply_or_fetch(self):
        app=FakeApplication();handler=register_development_analyze(app,self.service,allowed_chat_ids={123})
        message=types.SimpleNamespace(text='/analyze NBA '+DAY+' 19 vs 2',reply_text=AsyncMock())
        update=types.SimpleNamespace(effective_chat=types.SimpleNamespace(id=999),effective_message=message)
        await handler.callback(update,types.SimpleNamespace(application=app))
        update.effective_chat.id=123;app.bot_data['deployment_scope']='PRODUCTION'
        await handler.callback(update,types.SimpleNamespace(application=app))
        message.reply_text.assert_not_awaited();self.backend.load_inputs.assert_not_awaited()


    async def test_scope_change_while_backend_awaits_prevents_final_reply(self):
        app=FakeApplication();handler=register_development_analyze(app,self.service,allowed_chat_ids={123})
        async def load(league,day):
            app.bot_data['deployment_scope']='PRODUCTION';return self.inputs
        self.backend.load_inputs.side_effect=load
        message=types.SimpleNamespace(text='/analyze NBA '+DAY+' 19 vs 2',reply_text=AsyncMock())
        update=types.SimpleNamespace(effective_chat=types.SimpleNamespace(id=123),effective_message=message)
        await handler.callback(update,types.SimpleNamespace(application=app))
        message.reply_text.assert_not_awaited()

    async def test_permission_expiring_after_capture_prevents_delivery(self):
        for policy in self.registry.values():policy['expires_at_utc']=NOW+1
        self.pin=digest(self.registry);self.inputs=dict(schedules=[self.seal()],history=history(self.registry),model=synthetic_model())
        self.backend.load_inputs.return_value=self.inputs
        self.service=DevelopmentAnalysisService(self.backend,allow_synthetic=True,registry=self.registry,registry_pin=self.pin,clock=lambda:self.current)
        self.assertEqual((await self.analyze())['status'],'PREDICTED_EXPERIMENTAL')
        self.current=NOW+2
        self.assertEqual((await self.analyze())['reason'],'SOURCE_PERMISSION_EXPIRED_AT_DELIVERY')


class RegistrationBoundaryTests(TestCase):
    def test_production_running_duplicate_handler_and_missing_allowlist_are_refused(self):
        service=DevelopmentAnalysisService()
        for app in [FakeApplication('PRODUCTION'),FakeApplication(running=True)]:
            with self.subTest(app=app),self.assertRaises(ValueError):register_development_analyze(app,service,allowed_chat_ids={1})
        with self.assertRaises(ValueError):register_development_analyze(FakeApplication(),service,allowed_chat_ids=set())
        app=FakeApplication();app.add_handler(CommandHandler('analyze',AsyncMock()))
        with self.assertRaisesRegex(ValueError,'EXISTING_ANALYZE'):register_development_analyze(app,service,allowed_chat_ids={1})
        with self.assertRaises(ValueError):DevelopmentAnalysisService(mode='PRODUCTION')

    def test_import_does_not_load_secret_dependent_main_or_start_bot(self):
        self.assertNotIn('main',sys.modules)
        with self.assertRaises(ValueError):parse_request('/analyze NBA 2026-1-1 A vs B')

class FrozenBackendBoundaryTests(IsolatedAsyncioTestCase):
    def bundle(self):
        p=dict(format='FAZ43_DEVELOPMENT_INPUT_BUNDLE_V1',partitions={'NBA:'+DAY:dict(schedules=[],history=[],model={})})
        return dict(payload=p,sha256=digest(p))

    async def test_pinned_backend_preserves_original_and_has_no_cross_day_fallback(self):
        from faz43_development import FrozenInputsBackend
        s=self.bundle();b=FrozenInputsBackend(s,trusted_sha256=s['sha256']);s['payload']['partitions'].clear()
        out=await b.load_inputs('NBA',DAY);out['history'].append('mutation')
        self.assertEqual((await b.load_inputs('NBA',DAY))['history'],[])
        self.assertIsNone(await b.load_inputs('NBA','2026-11-07'))

    async def test_rehashed_bundle_without_trusted_pin_and_unknown_format_are_refused(self):
        from faz43_development import FrozenInputsBackend
        s=self.bundle();pin=s['sha256'];s['payload']['partitions'].clear();s['sha256']=digest(s['payload'])
        with self.assertRaisesRegex(ValueError,'PIN_MISMATCH'):FrozenInputsBackend(s,trusted_sha256=pin)
        s=self.bundle();s['payload']['format']='PRODUCTION';s['sha256']=digest(s['payload'])
        with self.assertRaisesRegex(ValueError,'BUNDLE_SCHEMA'):FrozenInputsBackend(s,trusted_sha256=s['sha256'])

    async def test_local_bundle_read_is_unchanged_and_symlink_is_refused(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from faz43_development import FrozenInputsBackend
        with TemporaryDirectory() as folder:
            s=self.bundle();p=Path(folder)/'bundle.json';p.write_text(json.dumps(s));before=p.read_bytes()
            backend=FrozenInputsBackend.from_file(p,trusted_sha256=s['sha256']);await backend.load_inputs('NBA',DAY)
            self.assertEqual(p.read_bytes(),before)
            link=Path(folder)/'link';link.symlink_to(p)
            with self.assertRaises(ValueError):FrozenInputsBackend.from_file(link,trusted_sha256=s['sha256'])
