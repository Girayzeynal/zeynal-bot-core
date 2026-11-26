"""Exercise the main.py candidate profile with PTB and a loopback Bot API."""
import asyncio
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from aiohttp import web
from telegram.ext import Application

import main
from hybrid_engine import isolated_execution, test_bot
from hybrid_engine.stage_archived_model import stage
from tests.test_test_bot_bootstrap import ARCHIVE, COMMANDS, ENV, PACKET, ROOT


class MainStagingTests(IsolatedAsyncioTestCase):
    async def test_three_league_replays_and_persisted_button_through_main_polling(self):
        ready = asyncio.Event()
        incoming = asyncio.Queue()
        processed = {}
        responses = []
        methods = []
        applications = []
        human = dict(id=23, is_bot=False, first_name="Reader")
        chat = dict(id=17, type="private")

        async def api(request):
            method = request.path.rsplit("/", 1)[-1]
            methods.append(method)
            params = await request.post()
            if method == "getMe":
                result = dict(id=123456, is_bot=True, first_name="Offline", username=ENV["ZEYNAL_TEST_BOT_USERNAME"])
            elif method == "getWebhookInfo":
                result = dict(url="", has_custom_certificate=False, pending_update_count=0)
            elif method == "getUpdates":
                ready.set()
                await asyncio.sleep(0.03)
                result = [] if incoming.empty() else [incoming.get_nowait()]
            elif method in ("sendMessage", "editMessageText"):
                responses.append(dict(params))
                result = dict(message_id=100, date=1, chat=chat, text=params["text"])
            elif method in ("deleteWebhook", "answerCallbackQuery"):
                result = True
            else:
                raise AssertionError(method)
            return web.json_response(dict(ok=True, result=result))

        def idle_worker(coroutine):
            coroutine.close()
            return asyncio.create_task(asyncio.Event().wait())

        server = web.Application()
        server.router.add_post("/{path:.*}", api)
        runner = web.AppRunner(server)
        await runner.setup()
        self.addAsyncCleanup(runner.cleanup)
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = runner.addresses[0][1]

        def build_local(**kwargs):
            app = main_builder(**kwargs)
            applications.append(app)
            return app

        original_process = Application.process_update

        async def observe(app, update):
            await original_process(app, update)
            processed[update.update_id].set()

        async def dispatch(update):
            complete = processed[update["update_id"]] = asyncio.Event()
            incoming.put_nowait(update)
            await asyncio.wait_for(complete.wait(), 15)

        async def command(text, number):
            await dispatch(dict(update_id=number, message={
                "message_id": number, "date": 1, "chat": chat, "from": human, "text": text,
                "entities": [dict(type="bot_command", offset=0, length=len(text.split()[0]))],
            }))

        cwd = Path.cwd()
        main_builder = main.build_app
        with TemporaryDirectory() as tmp, ExitStack() as stack:
            stack.callback(os.chdir, cwd)
            root = Path(tmp)
            prepared = stage(PACKET, root)
            europe = root / "europe"
            packet = ROOT / "docs/evidence/europe-phase95-native-20261117.tar.gz"
            with tarfile.open(packet) as archive:
                for item in archive:
                    target = europe / item.name
                    self.assertTrue(item.isfile() and target.resolve().is_relative_to(europe))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.extractfile(item).read())
            def archive_hashes():
                return {p: hashlib.sha256(p.read_bytes()).digest() for p in europe.rglob("*.json")}
            original = archive_hashes()
            rows = json.loads(next(europe.glob("capture-*.json")).read_text())["payload"]["results"]
            args = test_bot.candidate_args(["--data-directory", tmp, "--archive-directory", str(ARCHIVE),
                "--europe-directory", str(europe), "--nba-model", prepared["path"], "--nba-model-sha", prepared["sha256"]])
            isolated_env={k:v for k,v in ENV.items() if k.startswith("ZEYNAL_TEST_")}
            isolated_env['ZEYNAL_RELEASE_SHA']='a'*40
            stack.enter_context(patch.dict(os.environ, isolated_env, clear=True))
            stack.enter_context(patch.object(Application, "process_update", observe))
            stack.enter_context(patch.object(main, "PORT", 0))
            stack.enter_context(patch.object(main, "TELEGRAM_BOT_TOKEN", None))
            stack.enter_context(patch.object(main, "build_app", build_local))
            stack.enter_context(patch.object(test_bot, "Application", SimpleNamespace(
                builder=lambda: Application.builder().base_url(f"http://127.0.0.1:{port}/bot"))))
            stack.enter_context(patch.object(isolated_execution, "background_task", idle_worker))
            download = stack.enter_context(patch.object(test_bot, "fetch_document", side_effect=AssertionError("offline replay")))
            bulletin = stack.enter_context(patch("hybrid_engine.iddaa_bulletin.Bulletin.review", return_value="İddaa · örnek bülten"))
            callback = None
            for boot in range(2):
                ready.clear()
                task = asyncio.create_task(main.main_async(args))
                try:
                    await asyncio.wait_for(ready.wait(), 15)
                    app = applications[-1]
                    self.assertTrue(app.running and app.updater.running)
                    self.assertEqual(app.bot_data["entry_profile"], "MAIN_STAGING")
                    if boot == 0:
                        await command("/barem NBA", 90)
                        self.assertEqual(responses[-1]["text"], "İddaa · örnek bülten")
                        bulletin.assert_called_once_with("NBA", None)
                        await command(COMMANDS[0], 1)
                        self.assertTrue(any("NBA ARŞİV REPLAY" in r["text"] for r in responses))
                        for i, row in enumerate(rows, 2):
                            responses.clear()
                            await command(f"/analyze {row['league']} {row['day']} {row['home']} vs {row['away']}", i)
                            card = next(r for r in responses if "reply_markup" in r)
                            self.assertIn(row["league"], card["text"])
                            if row["league"] == "EUROCUP":
                                buttons = json.loads(card["reply_markup"])["inline_keyboard"]
                                callback = next(b["callback_data"] for line in buttons for b in line if ":period" in b["callback_data"])
                        class PartialReports:
                            def read(self, league, fixture):
                                if league == "EUROLEAGUE":
                                    raise ValueError("REPORT_NATIVE_SCORE_CONFLICT")
                                return {"status":"VERIFIED_LIVE_REPORT","forecasts":[],"groups":[]}
                        def bad_candidate():
                            raise TimeoutError
                        app.bot_data["ledger_reports"] = PartialReports()
                        app.bot_data["current_assessments"] = SimpleNamespace(render_performance=bad_candidate)
                        await command("/accuracy all", 89)
                        self.assertIn("NBA: 0 model", responses[-1]["text"])
                        self.assertIn("EUROCUP: 0 model", responses[-1]["text"])
                        self.assertIn("EUROLEAGUE · Arşiv okunamadı", responses[-1]["text"])
                        self.assertIn("REPORT_TIMEOUT", responses[-1]["text"])
                        await command('/test acceptance',91)
                        result=json.loads(responses[-1]['text'])
                        proof=result['accuracy']
                        self.assertEqual(result['running_release_sha'],'a'*40)
                        self.assertEqual(proof['report_status'],'PARTIAL_REPORT')
                        self.assertEqual(proof['leagues']['EUROLEAGUE']['error'],'REPORT_NATIVE_SCORE_CONFLICT')
                        self.assertEqual(proof['returned_parts'],proof['expected_parts'])
                        self.assertEqual(proof['verified_parts'],0)
                        self.assertEqual(proof['status'],'UNCONFIRMED')  # loopback API
                        await command('/test modelaudit',92)
                        audit_message=responses[-1]['text']
                        self.assertIn('YAYIMLANMIŞ ADAYLARIN EŞLEŞTİRİLMİŞ HATA DENETİMİ',audit_message)
                        self.assertIn('NBA · uygun sonuçlu maç 0',audit_message)
                        self.assertIn('EUROCUP · uygun sonuçlu maç 0',audit_message)
                        self.assertIn('EUROLEAGUE · Arşiv okunamadı · REPORT_NATIVE_SCORE_CONFLICT',audit_message)
                    else:
                        self.assertIsNotNone(callback)
                        await dispatch(dict(update_id=10, callback_query={
                            "id": "10", "from": human, "chat_instance": "local", "data": callback,
                            "message": dict(message_id=100, date=1, chat=chat),
                        }))
                        self.assertIn("answerCallbackQuery", methods)
                        self.assertIn("editMessageText", methods)
                        self.assertIn("1Q", responses[-1]["text"])
                finally:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                self.assertFalse(app.running or app.updater.running)
                self.assertEqual(original, archive_hashes())
            download.assert_not_called()

    async def test_staging_without_dedicated_identity_stops_before_polling(self):
        args = test_bot.candidate_args([])
        with patch.dict(os.environ, {}, clear=True), patch.object(main, "start_health") as health:
            with self.assertRaisesRegex(ValueError, "STAGING_REQUIRES_DEDICATED_BOT"):
                await main.main_async(args)
            health.assert_not_called()
