"""Exercise the real /analyze handler without importing bot startup or network."""
import ast
import asyncio
import datetime
import html
import logging
import pathlib
import types
import unittest
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock
from typing import Any, Tuple


def load_handler():
    path = pathlib.Path(__file__).resolve().parents[1] / "main.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {"parse_analyze", "baseline_quality_reason",
             "baseline_failure_message", "analyze_command"}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in names or isinstance(node, ast.AsyncFunctionDef)
                 and node.name in names]
    reasons = [node for node in tree.body if isinstance(node, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "BASELINE_REASON_TR"
                       for t in node.targets)]
    namespace = {"Any": Any, "Update": Any, "ContextTypes": types.SimpleNamespace(DEFAULT_TYPE=Any), "math": __import__("math"), "html": html,
                 "datetime": datetime.datetime, "timezone": datetime.timezone, "ZoneInfo": ZoneInfo, "Tuple": Tuple,
                 "logger": logging.getLogger("telegram-test")}
    exec(compile(ast.fix_missing_locations(
        ast.Module(body=reasons + functions, type_ignores=[])), str(path), "exec"),
         namespace)
    async def fake_fixture(_adapter, _date, _home, _away):
        return {"provider_fixture_id": "401909924"}
    namespace["resolve_nba_fixture"] = fake_fixture
    return namespace["analyze_command"]


class TelegramAnalyzeFailClosedTests(unittest.TestCase):
    def test_missing_baseline_never_calls_engine(self):
        async def scenario():
            handler = load_handler()
            today = (datetime.datetime.now(ZoneInfo("Europe/Istanbul")).date()
                     + datetime.timedelta(days=1)).isoformat()
            update = types.SimpleNamespace(message=types.SimpleNamespace(
                text=f"/analyze NBA {today} Home vs Away", reply_text=AsyncMock()))
            bootstrapper = types.SimpleNamespace(ensure_async=AsyncMock(return_value=None))
            engine = types.SimpleNamespace(run_prematch=AsyncMock())
            context = types.SimpleNamespace(application=types.SimpleNamespace(
                bot_data={"faz13": engine, "baseline_bootstrapper": bootstrapper}))
            await handler(update, context)
            engine.run_prematch.assert_not_awaited()
            self.assertIn("Analiz oluşturulmadı", update.message.reply_text.await_args.args[0])
        asyncio.run(scenario())

    def test_past_fixture_never_calls_provider_or_engine(self):
        async def scenario():
            handler = load_handler()
            yesterday = (datetime.datetime.now(ZoneInfo("Europe/Istanbul")).date()
                         - datetime.timedelta(days=1)).isoformat()
            update = types.SimpleNamespace(message=types.SimpleNamespace(
                text=f"/analyze NBA {yesterday} Home vs Away",
                reply_text=AsyncMock()))
            bootstrapper = types.SimpleNamespace(ensure_async=AsyncMock())
            engine = types.SimpleNamespace(run_prematch=AsyncMock())
            context = types.SimpleNamespace(application=types.SimpleNamespace(
                bot_data={"faz13": engine, "baseline_bootstrapper": bootstrapper}))
            await handler(update, context)
            bootstrapper.ensure_async.assert_not_awaited()
            engine.run_prematch.assert_not_awaited()
            self.assertIn("Tarihsel veri kesiti", update.message.reply_text.await_args.args[0])
        asyncio.run(scenario())

    def test_invalid_command_never_calls_provider_or_engine(self):
        async def scenario():
            handler = load_handler()
            update = types.SimpleNamespace(message=types.SimpleNamespace(
                text="/analyze NBA invalid Home vs Away", reply_text=AsyncMock()))
            bootstrapper = types.SimpleNamespace(ensure_async=AsyncMock())
            engine = types.SimpleNamespace(run_prematch=AsyncMock())
            context = types.SimpleNamespace(application=types.SimpleNamespace(
                bot_data={"faz13": engine, "baseline_bootstrapper": bootstrapper}))
            await handler(update, context)
            bootstrapper.ensure_async.assert_not_awaited()
            engine.run_prematch.assert_not_awaited()
            self.assertIn("Parametre hatasi", update.message.reply_text.await_args.args[0])
        asyncio.run(scenario())

    def test_success_renders_telegram_html(self):
        async def scenario():
            handler = load_handler()
            handler.__globals__["PrematchRequest"] = lambda **kwargs: types.SimpleNamespace(**kwargs)
            handler.__globals__["Faz13CoreOutput"] = types.SimpleNamespace
            tomorrow = (datetime.datetime.now(ZoneInfo("Europe/Istanbul")).date()
                        + datetime.timedelta(days=1)).isoformat()
            update = types.SimpleNamespace(message=types.SimpleNamespace(
                text=f"/analyze NBA {tomorrow} Home vs Away", reply_text=AsyncMock()))
            baseline = types.SimpleNamespace(
                games_played=10, updated_at=datetime.datetime.now(datetime.timezone.utc).timestamp(),
                source="verified")
            bootstrapper = types.SimpleNamespace(ensure_async=AsyncMock(return_value=baseline))
            result = types.SimpleNamespace(meta={"data_quality": "VERIFIED"}, render_html=lambda: "<b>Verified</b>")
            faz22 = types.SimpleNamespace(score_and_finalize=lambda core: core)
            faz23 = types.SimpleNamespace(apply_decision=lambda core: core, record_snapshot=AsyncMock())
            engine = types.SimpleNamespace(run_prematch=AsyncMock(return_value=result))
            context = types.SimpleNamespace(application=types.SimpleNamespace(
                bot_data={"faz13": engine, "baseline_bootstrapper": bootstrapper,
                          "nba_fixture_adapter": object(),
                          "faz22": faz22, "faz23": faz23}))
            # Isolate the presentation contract from baseline quality policy.
            handler.__globals__["baseline_quality_reason"] = lambda *_args: "usable"
            await handler(update, context)
            engine.run_prematch.assert_awaited_once()
            faz23.record_snapshot.assert_awaited_once_with(result)
            self.assertEqual(update.message.reply_text.await_args.args[0], "<b>Verified</b>")
            self.assertEqual(update.message.reply_text.await_args.kwargs["parse_mode"], "HTML")
        asyncio.run(scenario())

    def test_missing_quality_provenance_blocks_downstream_engines(self):
        async def scenario():
            handler = load_handler()
            handler.__globals__["PrematchRequest"] = lambda **kwargs: types.SimpleNamespace(**kwargs)
            handler.__globals__["Faz13CoreOutput"] = types.SimpleNamespace
            handler.__globals__["baseline_quality_reason"] = lambda *_args: "usable"
            tomorrow = (datetime.datetime.now(ZoneInfo("Europe/Istanbul")).date()
                        + datetime.timedelta(days=1)).isoformat()
            update = types.SimpleNamespace(message=types.SimpleNamespace(
                text=f"/analyze NBA {tomorrow} Home vs Away", reply_text=AsyncMock()))
            bootstrapper = types.SimpleNamespace(ensure_async=AsyncMock(return_value=object()))
            engine = types.SimpleNamespace(run_prematch=AsyncMock(return_value=types.SimpleNamespace(meta={})))
            faz22 = types.SimpleNamespace(score_and_finalize=unittest.mock.Mock())
            faz23 = types.SimpleNamespace(apply_decision=unittest.mock.Mock(), record_snapshot=AsyncMock())
            context = types.SimpleNamespace(application=types.SimpleNamespace(bot_data={
                "nba_fixture_adapter": object(),
                "faz13": engine, "baseline_bootstrapper": bootstrapper,
                "faz22": faz22, "faz23": faz23,
            }))
            await handler(update, context)
            engine.run_prematch.assert_awaited_once()
            faz22.score_and_finalize.assert_not_called()
            faz23.apply_decision.assert_not_called()
            faz23.record_snapshot.assert_not_awaited()
            self.assertIn("dahili bir hata", update.message.reply_text.await_args.args[0])
        asyncio.run(scenario())

    def test_invalid_faz22_output_blocks_snapshot_and_reply(self):
        async def scenario():
            handler = load_handler()
            handler.__globals__["PrematchRequest"] = lambda **kwargs: types.SimpleNamespace(**kwargs)
            handler.__globals__["Faz13CoreOutput"] = types.SimpleNamespace
            handler.__globals__["baseline_quality_reason"] = lambda *_args: "usable"
            tomorrow = (datetime.datetime.now(ZoneInfo("Europe/Istanbul")).date()
                        + datetime.timedelta(days=1)).isoformat()
            update = types.SimpleNamespace(message=types.SimpleNamespace(
                text=f"/analyze NBA {tomorrow} Home vs Away", reply_text=AsyncMock()))
            core = types.SimpleNamespace(meta={"data_quality": "VERIFIED"})
            engine = types.SimpleNamespace(run_prematch=AsyncMock(return_value=core))
            faz22 = types.SimpleNamespace(score_and_finalize=lambda _core: None)
            faz23 = types.SimpleNamespace(apply_decision=unittest.mock.Mock(), record_snapshot=AsyncMock())
            context = types.SimpleNamespace(application=types.SimpleNamespace(bot_data={
                "faz13": engine,
                "baseline_bootstrapper": types.SimpleNamespace(ensure_async=AsyncMock(return_value=object())),
                "faz22": faz22, "faz23": faz23,
            }))
            await handler(update, context)
            faz23.apply_decision.assert_not_called()
            faz23.record_snapshot.assert_not_awaited()
            self.assertIn("dahili bir hata", update.message.reply_text.await_args.args[0])
        asyncio.run(scenario())

    def test_provider_exception_never_calls_engine(self):
        async def scenario():
            handler = load_handler()
            today = (datetime.datetime.now(ZoneInfo("Europe/Istanbul")).date()
                     + datetime.timedelta(days=1)).isoformat()
            update = types.SimpleNamespace(message=types.SimpleNamespace(
                text=f"/analyze NBA {today} Home vs Away", reply_text=AsyncMock()))
            bootstrapper = types.SimpleNamespace(ensure_async=AsyncMock(
                side_effect=RuntimeError("provider unavailable")))
            engine = types.SimpleNamespace(run_prematch=AsyncMock())
            context = types.SimpleNamespace(application=types.SimpleNamespace(
                bot_data={"faz13": engine, "baseline_bootstrapper": bootstrapper}))
            await handler(update, context)
            engine.run_prematch.assert_not_awaited()
            self.assertIn("Veri sağlayıcısı hatası", update.message.reply_text.await_args.args[0])
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
