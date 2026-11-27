"""Read-only provenance observation; local HTTP is not real Telegram delivery."""
import importlib
import json
import os
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase,TestCase
from unittest.mock import AsyncMock,patch

from aiohttp import ClientSession
from core.team_identity import digest
from hybrid_engine.runtime_identity import ObservedAnalysis,describe,install


class RuntimeIdentityTests(IsolatedAsyncioTestCase):
    async def test_proxy_keeps_report_object_and_lazy_ledger_and_is_idempotent(self):
        snapshot=dict(model_version='SYNTHETIC_MODEL',model_digest='a'*64)
        report=dict(status='OK',snapshot=snapshot,new_record=True)
        base=SimpleNamespace(ledger=None,analyze=AsyncMock(return_value=report));state={'verified_analysis_service':base}
        install(state);proxy=state['verified_analysis_service'];install(state)
        self.assertIs(state['verified_analysis_service'],proxy);self.assertIsNone(proxy.ledger)
        ledger=object();base.ledger=ledger;self.assertIs(proxy.ledger,ledger)
        got=await proxy.analyze('NBA','date','home','away');self.assertIs(got,report)
        base.analyze.assert_awaited_once_with('NBA','date','home','away')
        r=describe(state)['last_analysis']['NBA']
        self.assertEqual(r['model_digest'],'a'*64);self.assertEqual(r['snapshot_sha256'],digest(snapshot))
        self.assertFalse(r['actual_telegram_delivery_verified'])

    async def test_abstain_has_no_model_and_failed_analysis_is_not_falsely_observed(self):
        base=SimpleNamespace(analyze=AsyncMock(return_value={'status':'ABSTAIN'}));state={}
        proxy=ObservedAnalysis(base,state);await proxy.analyze('NBA')
        self.assertIsNone(state['last_analysis_identity']['NBA']['model_digest'])
        before=json.dumps(state);base.analyze.side_effect=ValueError('source blocked')
        with self.assertRaises(ValueError):await proxy.analyze('NBA')
        self.assertEqual(json.dumps(state),before)

    async def test_bad_optional_metadata_cannot_prevent_original_response(self):
        report=dict(status='FROZEN_REPLAY_OK',snapshot={'models':None});base=SimpleNamespace(analyze=AsyncMock(return_value=report));state={}
        result=await ObservedAnalysis(base,state).analyze('NBA')
        self.assertIs(result,report);self.assertEqual(state['runtime_identity_capture_status'],'UNAVAILABLE_REPORT_METADATA')

    async def test_european_context_observed_and_public_values_do_not_export_arbitrary_text(self):
        report={'status':'OK','forecast_sha256':'c'*64};base=SimpleNamespace(analyze=AsyncMock(return_value=report))
        state={'premium_reports':{'token':{'europe_context':{'original_forecast_sha256':'c'*64,
            'model_version':'BAYES_TEAM_ATTACK_DEFENSE_V1','model_digest':'d'*64}}}}
        await ObservedAnalysis(base,state).analyze('EUROCUP')
        self.assertEqual(state['last_analysis_identity']['EUROCUP']['model_digest'],'d'*64)
        base.analyze.return_value={'status':'private value /secret','snapshot':{'model_version':'token=secret','model_digest':'not-a-pin'}}
        await ObservedAnalysis(base,state).analyze('NBA');out=json.dumps(describe(state))
        self.assertNotIn('/secret',out);self.assertNotIn('token=secret',out)

    async def test_local_http_runtime_endpoint_preserves_ready_contract(self):
        with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'123456:SYNTHETIC_ONLY','ZEYNAL_RELEASE_SHA':'e'*40}):
            main=importlib.import_module('main')
            app=SimpleNamespace(bot_data={},running=True,updater=SimpleNamespace(running=True))
            with patch.object(main,'PORT',0):runner=await main.start_health(app)
            try:
                port=runner.addresses[0][1]
                async with ClientSession() as client:
                    async with client.get(f'http://127.0.0.1:{port}/ready') as r:
                        self.assertEqual(r.status,200);self.assertEqual(await r.json(),{'ready':True,'release_sha':'e'*40})
                    async with client.get(f'http://127.0.0.1:{port}/analysis-runtime') as r:
                        self.assertEqual(r.status,200);body=await r.json()
                        self.assertEqual(body['identity_status'],'SERVICE_LOADED_ANALYSIS_NOT_OBSERVED')
                        self.assertEqual(body['provider_queries'],0);self.assertEqual(body['reported_release_sha'],'e'*40)
                    app.running=False
                    async with client.get(f'http://127.0.0.1:{port}/ready') as r:self.assertEqual(r.status,503)
            finally:await runner.cleanup()


class PublicRuntimeTests(TestCase):
    def test_only_baseline_location_category_is_exposed_not_paths_or_environment(self):
        state={'baseline_store':SimpleNamespace(base_dir='/app/private/key-like-path'),
               'secret':'SENSITIVE_TEST_TEXT'}
        with patch.dict(os.environ,{'ZEYNAL_RELEASE_SHA':'invalid','PRIVATE_TEST_KEY':'SENSITIVE_TEST_TEXT'}):r=describe(state)
        self.assertEqual(r['legacy_baseline_location'],'APPLICATION_FILESYSTEM_PATH')
        self.assertIsNone(r['reported_release_sha']);self.assertNotIn('SENSITIVE_TEST_TEXT',json.dumps(r))
        self.assertNotIn('key-like-path',json.dumps(r));self.assertFalse(r['ledger_path_exposed'])

class IsolatedRuntimeCommandTests(IsolatedAsyncioTestCase):
    async def test_runtime_command_uses_real_ptb_handler_and_synthetic_bot_api_without_provider_requests(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from telegram import Update
        from telegram.ext import Application
        from hybrid_engine.frozen_archive import FrozenArchive
        from hybrid_engine.test_bot import install_isolated_services
        from tests.test_current_roster_telegram import ReviewBotAPI
        from tests.test_season_archive_audit import NOW
        archive=FrozenArchive(Path(__file__).resolve().parents[1]/'docs/prospective/euroleague-20261112')
        with TemporaryDirectory() as tmp:
            api=ReviewBotAPI();app=Application.builder().token('123456:SYNTHETIC_ONLY').request(api).build()
            never=AsyncMock(side_effect=AssertionError('NO_PROVIDER_REQUEST'))
            install_isolated_services(app,archive,tmp,chat_id=17,transport=never)
            await app.initialize()
            try:
                update=Update.de_json(dict(update_id=1,message=dict(message_id=1,date=NOW,
                    chat=dict(id=17,type='private'),**{'from':dict(id=23,is_bot=False,first_name='Synthetic')},
                    text='/test runtime',entities=[dict(type='bot_command',offset=0,length=5)])),app.bot)
                await app.process_update(update)
                text='\n'.join(api.sent)
                self.assertIn('READ_ONLY_ANALYSIS_RUNTIME_IDENTITY_V1',text)
                self.assertIn('SERVICE_LOADED_ANALYSIS_NOT_OBSERVED',text)
                never.assert_not_called()
            finally:await app.shutdown()

class RuntimeBusyReasonTests(IsolatedAsyncioTestCase):
    async def test_runtime_shows_latest_busy_reason_not_previous_success(self):
        base=SimpleNamespace(analyze=AsyncMock(return_value=dict(status='ABSTAIN',reason='EUROPE_PREMATCH_INFERENCE_BUSY')))
        state=dict(europe_auto_scheduler_enabled=False)
        await ObservedAnalysis(base,state).analyze('EUROLEAGUE')
        report=describe(state)
        self.assertEqual(report['last_analysis']['EUROLEAGUE']['reason'],'EUROPE_PREMATCH_INFERENCE_BUSY')
        self.assertFalse(report['europe_auto_scheduler_enabled'])
        self.assertEqual(report['provider_queries_scope'],'THIS_DIAGNOSTIC_ONLY')
