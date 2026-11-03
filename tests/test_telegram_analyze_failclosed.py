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
