"""Actual CLI bootstrap + local HTTP Bot API double. Never real Telegram E2E."""
import asyncio
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import importlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import time
from types import SimpleNamespace
from urllib.parse import parse_qs
from unittest import TestCase
from unittest.mock import patch

from telegram import Update
from telegram.ext import Application

from hybrid_engine import test_bot
from hybrid_engine.telegram_evidence import plaintext

ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT/'docs/prospective/euroleague-20261112'
PACKET=ROOT/'docs/evidence/nba-phase843-prospective-native-20261113.tar.gz'
ENV=dict(ZEYNAL_TEST_BOT_TOKEN='123456:SYNTHETIC_LOCAL_ONLY',ZEYNAL_TEST_BOT_ID='123456',
    ZEYNAL_TEST_BOT_USERNAME='zeynal_test_bot',ZEYNAL_TEST_CHAT_ID='17',TELEGRAM_BOT_TOKEN='123456:SYNTHETIC_LOCAL_ONLY')
COMMANDS=[
    '/analyze NBA 2026-11-13 Philadelphia 76ers vs Toronto Raptors',
    '/analyze NBA 2026-11-13 Washington Wizards vs Detroit Pistons',
    '/analyze NBA 2026-11-13 Minnesota Timberwolves vs Dallas Mavericks',
    '/analyze NBA 2026-11-13 Phoenix Suns vs Charlotte Hornets',
    '/analyze EUROLEAGUE 2026-11-12 Real Madrid vs Crvena Zvezda Meridianbet Belgrade']


class BootstrapTests(TestCase):
    def exercise(self,*,identity_ok=True,webhook='',extra_args=()):
        calls=[];messages=[];started=[];cwd=Path.cwd()
        class API(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                name=self.path.rsplit('/',1)[-1];calls.append(name)
                params=parse_qs(self.rfile.read(int(self.headers.get('Content-Length','0'))).decode())
                if name=='getMe':result=dict(id=123456 if identity_ok else 999,is_bot=True,first_name='Synthetic',username='zeynal_test_bot')
                elif name=='getWebhookInfo':result=dict(url=webhook,has_custom_certificate=False,pending_update_count=0)
                elif name=='sendMessage':
                    raw=params['text'][0];messages.append(raw)
                    result=dict(message_id=100+len(messages),date=int(time.time()),chat=dict(id=17,type='private'),
                        text=plaintext(raw,params.get('parse_mode',[''])[0]))
                else:raise AssertionError('Unexpected mock Bot API method: '+name)
                body=json.dumps(dict(ok=True,result=result)).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)))
                self.end_headers();self.wfile.write(body)
        server=ThreadingHTTPServer(('127.0.0.1',0),API);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        port=server.server_address[1]
        def builder():return Application.builder().base_url(f'http://127.0.0.1:{port}/bot').base_file_url(f'http://127.0.0.1:{port}/file/bot')
        def run_polling(app,**kwargs):
            self.assertEqual(kwargs,dict(bootstrap_retries=0,drop_pending_updates=False))
            loop=asyncio.get_event_loop()
            async def run():
                initialized=False
                try:
                    await app.initialize();initialized=True
                    await app.post_init(app)
                    started.append(True);await app.start()
                    for i,text in enumerate(COMMANDS):
                        update=Update.de_json(dict(update_id=i+1,message=dict(message_id=i+1,date=int(time.time()),
                            chat=dict(id=17,type='private'),**{'from':dict(id=23,is_bot=False,first_name='Synthetic human')},
                            text=text,entities=[dict(type='bot_command',offset=0,length=8)])),app.bot)
                        await app.process_update(update)
                    await app.update_queue.join()
                    self.assertEqual(app.bot_data['test_results'].comparison()['settled_games'],0)
                finally:
                    if app.running:await app.stop()
                    if initialized:await app.shutdown()
                    if app.post_shutdown:await app.post_shutdown(app)
            try:loop.run_until_complete(run())
            finally:
                loop.run_until_complete(loop.shutdown_default_executor());loop.close();asyncio.set_event_loop(None)
        try:
            with TemporaryDirectory() as tmp,ExitStack() as stack:
                stack.enter_context(patch.dict(os.environ,ENV))
                application=importlib.import_module('main')
                stack.enter_context(patch.object(application,'TELEGRAM_BOT_TOKEN',ENV['TELEGRAM_BOT_TOKEN']))
                stack.enter_context(patch.object(test_bot,'Application',SimpleNamespace(builder=builder)))
                stack.enter_context(patch.object(Application,'run_polling',run_polling))
                download=stack.enter_context(patch.object(test_bot,'fetch_document',side_effect=AssertionError('No result polling/source downloads')))
                argv=['test_bot','--replay-only','--archive-directory',str(ARCHIVE),'--nba-replay-packet',str(PACKET),
                    '--data-directory',tmp,*extra_args]
                stack.enter_context(patch('sys.argv',argv))
                try:test_bot.main()
                finally:
                    os.chdir(cwd);download.assert_not_called()
                self.assertFalse(list(Path(tmp).glob('*ledger.sqlite')))
        finally:
            os.chdir(cwd);server.shutdown();thread.join(timeout=3);server.server_close()
            self.last_calls=list(calls);self.last_messages=list(messages)
        return calls,messages,started

    def test_cli_bootstrap_routes_four_nba_and_one_euroleague_command(self):
        calls,messages,started=self.exercise()
        self.assertTrue(started);self.assertIn('getMe',calls);self.assertIn('getWebhookInfo',calls)
        self.assertEqual(sum('NBA ARŞİV REPLAY' in m for m in messages),4)
        self.assertEqual(sum('ELITE HYBRID PRO' in m for m in messages),1)
        self.assertFalse(any('Analiz hizmeti kullanılamıyor' in m for m in messages))
        self.assertEqual(sum('NOT_CALIBRATED' in m for m in messages),4)
        self.assertNotIn('deleteWebhook',calls)

    def test_cli_mismatched_bot_identity_stops_before_commands(self):
        with self.assertRaisesRegex(ValueError,'TEST_BOT_SERVER_IDENTITY_MISMATCH'):self.exercise(identity_ok=False)
        self.assertEqual(self.last_messages,[]);self.assertNotIn('getWebhookInfo',self.last_calls)

    def test_cli_existing_webhook_is_not_removed_or_overwritten(self):
        with self.assertRaisesRegex(ValueError,'TEST_BOT_HAS_WEBHOOK'):self.exercise(webhook='https://synthetic.example.test/existing-hook')
        self.assertEqual(self.last_messages,[]);self.assertNotIn('deleteWebhook',self.last_calls)

    def test_cli_replay_only_rejects_a_live_model_before_api_calls(self):
        with self.assertRaisesRegex(ValueError,'REPLAY_ONLY_FORBIDS'):self.exercise(extra_args=('--nba-model','unused.json'))
        self.assertEqual(self.last_calls,[])

    def test_known_startup_failures_have_actionable_safe_codes(self):
        for code in ('TEST_BOT_SERVER_IDENTITY_MISMATCH','TEST_BOT_HAS_WEBHOOK_POLLING_NOT_STARTED','NBA_REPLAY_PACKET_SHA256'):
            with self.subTest(code=code):self.assertEqual(test_bot.failure_report(ValueError(code))['reason'],code)

    def test_arbitrary_api_errors_do_not_disclose_token_urls_or_credentials(self):
        marker='SYNTHETIC_PRIVATE_MARKER'
        for error in (RuntimeError('https://api.telegram.org/bot123:'+marker+'/getMe'),ValueError(marker)):
            report=test_bot.failure_report(error)
            self.assertEqual(report['reason'],'ISOLATED_TEST_BOT_FAILED');self.assertNotIn(marker,json.dumps(report))
