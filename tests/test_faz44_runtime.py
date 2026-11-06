"""Adversarial fixtures are synthetic, never real prospective records."""
from copy import deepcopy
from unittest import TestCase,IsolatedAsyncioTestCase
from unittest.mock import AsyncMock,patch
import types

from prediction_inputs import digest
from faz41_adapters import capture
from faz42_schedule import seal_schedule
from faz42_snapshot import build_snapshot
from faz43_development import DevelopmentAnalysisService,register_development_analyze
from tests.test_faz42_history import NOW,history,permitted_registry
from tests.test_faz42_prospective import test_model as synthetic_model
from tests.test_faz33 import event

URL='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20261106'
START=NOW+3600


def inputs(registry,*,synthetic=True,schedule_age=60):
    pin=digest(registry)
    with patch('time.time',return_value=NOW-50):schedule=seal_schedule({'events':[event(START,'900000099')]},provider='ESPN',league='NBA',season_end_year=2027,
        source_url=URL,observed_at_utc=NOW-schedule_age,ingested_at_utc=NOW-55,usage='SYNTHETIC_TEST' if synthetic else 'LIVE_DISCOVERY',registry=registry,registry_pin=pin)
    records=history(registry)
    if not synthetic:
        converted=[]
        for o in records:
            p=o['payload']
            with patch('time.time',return_value=p['materialized_at_utc']):converted.append(capture(p['raw'],provider='ESPN',league='NBA',season_end_year=2027,
                observed_at_utc=p['observed_at_utc'],ingested_at_utc=p['ingested_at_utc'],usage='RETROSPECTIVE_RESEARCH',registry=registry,registry_pin=pin))
        records=converted
    model=synthetic_model()
    if not synthetic:model['payload']['purpose']='EXPERIMENTAL_DRY_RUN';model['sha256']=digest(model['payload'])
    return dict(schedules=[schedule],history=records,model=model)


class RuntimeManifestTests(TestCase):
    def setUp(self):
        self.timer=patch('time.time',return_value=NOW);self.timer.start();self.addCleanup(self.timer.stop)
        self.registry=permitted_registry();self.pin=digest(self.registry)

    def test_non_synthetic_forged_model_sha_is_abstain_before_simulation(self):
        i=inputs(self.registry,synthetic=False);s=i['schedules'][0];cid=s['payload']['fixtures'][0]['fixture']['canonical_id']
        out=build_snapshot(i['history'],s,cid,i['model'],cutoff_utc=NOW,minimum_team_games=2,registry=self.registry,registry_pin=self.pin)
        self.assertEqual(out['payload']['status'],'ABSTAIN')
        self.assertIsNone(out['payload']['prediction']);self.assertIsNone(out['payload']['simulation'])


class DeliveryRuntimeTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.timer=patch('time.time',return_value=NOW);self.timer.start();self.addCleanup(self.timer.stop)
        self.current=NOW;self.registry=permitted_registry();self.pin=digest(self.registry)
        self.i=inputs(self.registry);self.backend=types.SimpleNamespace(load_inputs=AsyncMock(return_value=self.i))
        self.service=DevelopmentAnalysisService(self.backend,allow_synthetic=True,registry=self.registry,registry_pin=self.pin,clock=lambda:self.current)
        self.command='/analyze NBA 2026-11-06 19 vs 2'

    async def test_runtime_mode_change_after_registration_prevents_reply(self):
        app=types.SimpleNamespace(bot_data={'deployment_scope':'DEVELOPMENT'},running=False,handlers={},add_handler=lambda h:None)
        handler=register_development_analyze(app,self.service,allowed_chat_ids={123})
        async def load(league,day):self.service.mode='PRODUCTION';return self.i
        self.backend.load_inputs.side_effect=load
        message=types.SimpleNamespace(text=self.command,reply_text=AsyncMock())
        update=types.SimpleNamespace(effective_chat=types.SimpleNamespace(id=123),effective_message=message)
        await handler.callback(update,types.SimpleNamespace(application=app))
        message.reply_text.assert_not_awaited()

    async def test_disabling_synthetic_mode_invalidates_cached_synthetic_snapshot(self):
        self.assertEqual((await self.service.analyze(self.command))['status'],'PREDICTED_EXPERIMENTAL')
        self.service.allow_synthetic=False
        result=await self.service.analyze(self.command)
        self.assertEqual(result['status'],'ABSTAIN');self.assertEqual(result['reason'],'SYNTHETIC_SOURCE_REFUSED')

    async def test_schedule_freshness_is_checked_at_delivery_not_just_original_cutoff(self):
        self.i=inputs(self.registry,schedule_age=299);self.backend.load_inputs.return_value=self.i
        self.assertEqual((await self.service.analyze(self.command))['status'],'PREDICTED_EXPERIMENTAL')
        self.current=NOW+2
        result=await self.service.analyze(self.command)
        self.assertEqual(result['status'],'ABSTAIN');self.assertEqual(result['reason'],'STALE_SCHEDULE_AT_DELIVERY')

    async def test_delivery_clock_cannot_move_before_snapshot_creation(self):
        self.assertEqual((await self.service.analyze(self.command))['status'],'PREDICTED_EXPERIMENTAL')
        self.current=NOW-1
        self.assertEqual((await self.service.analyze(self.command))['reason'],'DELIVERY_CLOCK_REVERSED')


class ExecutionCodeBindingTests(TestCase):
    def setUp(self):
        self.timer=patch('time.time',return_value=NOW);self.timer.start();self.addCleanup(self.timer.stop)
        self.registry=permitted_registry();self.pin=digest(self.registry);self.i=inputs(self.registry,synthetic=False)

    def build(self):
        s=self.i['schedules'][0];cid=s['payload']['fixtures'][0]['fixture']['canonical_id']
        return build_snapshot(self.i['history'],s,cid,self.i['model'],cutoff_utc=NOW,minimum_team_games=2,registry=self.registry,registry_pin=self.pin)

    def test_current_code_manifest_ignores_only_new_collection_clock(self):
        from faz42_snapshot import verify_execution_manifest
        current=deepcopy(self.i['model']);current['payload']['materialized_at_utc']=NOW;current['sha256']=digest(current['payload'])
        with patch('faz42_snapshot.model_manifest',return_value=current):self.assertTrue(verify_execution_manifest(self.i['model']))
        current['payload']['git_sha']='f'*40;current['sha256']=digest(current['payload'])
        with patch('faz42_snapshot.model_manifest',return_value=current),self.assertRaisesRegex(ValueError,'DOES_NOT_MATCH_RUNTIME'):
            verify_execution_manifest(self.i['model'])

    def test_source_change_during_prediction_removes_forecast(self):
        with patch('faz42_snapshot.verify_execution_manifest',side_effect=[True,ValueError('MODEL_SOURCE_CHANGED_DURING_GENERATION')]) as check:
            result=self.build()['payload']
        self.assertEqual(check.call_count,2);self.assertEqual(result['status'],'ABSTAIN');self.assertIsNone(result['prediction'])
        self.assertIsNone(result['simulation'])

    def test_historical_snapshot_validation_does_not_rebind_to_todays_code(self):
        from faz42_snapshot import validate_snapshot
        with patch('faz42_snapshot.verify_execution_manifest',return_value=True):s=self.build()
        with patch('faz42_snapshot.verify_execution_manifest',side_effect=ValueError('CHANGED')) as guard:
            self.assertEqual(validate_snapshot(s,registry=self.registry,registry_pin=self.pin)['status'],'PREDICTED_EXPERIMENTAL')
            guard.assert_not_called()
