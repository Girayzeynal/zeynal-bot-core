"""Runtime failure injection for Telegram application lifecycle."""
import asyncio
import importlib
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:TEST_TOKEN_FOR_CI")
os.environ.setdefault("API_SPORTS_KEY", "TEST_KEY_FOR_CI")


class LifecycleRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_polling_start_failure_cleans_up(self):
        main = importlib.import_module("main")
        events = []

        def step(name, fail=False):
            async def call(*args, **kwargs):
                events.append(name)
                if fail:
                    raise RuntimeError("injected polling failure")
            return AsyncMock(side_effect=call)

        updater = MagicMock()
        updater.start_polling = step("polling.start", fail=True)
        updater.stop = step("polling.stop")
        app = MagicMock()
        app.initialize = step("initialize")
        app.start = step("app.start")
        app.stop = step("app.stop")
        app.shutdown = step("app.shutdown")
        app.bot.delete_webhook = step("delete_webhook")
        app.updater = updater
        runner = MagicMock()
        runner.cleanup = step("http.cleanup")

        with patch.object(main, "build_app", return_value=app), patch.object(
            main, "start_health", new=AsyncMock(return_value=runner)
        ):
            with self.assertRaisesRegex(RuntimeError, "injected polling failure"):
                await main.main_async()

        self.assertEqual(events, [
            "initialize", "delete_webhook", "app.start",
            "polling.start", "app.stop", "app.shutdown", "http.cleanup"
        ])
        updater.stop.assert_not_awaited()

    async def test_shutdown_failure_still_cleans_http_and_telegram(self):
        main = importlib.import_module("main")
        events = []

        def step(name, fail=False):
            async def call(*args, **kwargs):
                events.append(name)
                if fail:
                    raise RuntimeError("injected shutdown failure")
            return AsyncMock(side_effect=call)

        updater = MagicMock()
        updater.start_polling = step("polling.start")
        updater.stop = step("polling.stop", fail=True)
        app = MagicMock()
        app.initialize = step("initialize")
        app.start = step("app.start")
        app.stop = step("app.stop")
        app.shutdown = step("app.shutdown")
        app.bot.delete_webhook = step("delete_webhook")
        app.updater = updater
        app.bot_data = {"faz13": object(), "faz22": object(), "faz23": object()}
        runner = MagicMock()
        runner.cleanup = step("http.cleanup")

        async def scheduler(*args, **kwargs):
            raise RuntimeError("injected scheduler failure")

        with patch.object(main, "build_app", return_value=app), patch.object(
            main, "start_health", new=AsyncMock(return_value=runner)
        ), patch.object(main, "Faz17Engine", return_value=object()), patch.object(
            main, "scheduler_loop", new=scheduler
        ):
            with self.assertRaisesRegex(RuntimeError, "injected shutdown failure"):
                await main.main_async()

        self.assertIn("polling.stop", events)
        self.assertIn("app.stop", events)
        self.assertIn("app.shutdown", events)
        self.assertIn("http.cleanup", events)
        self.assertLess(events.index("polling.stop"), events.index("app.stop"))
        self.assertLess(events.index("app.stop"), events.index("app.shutdown"))
        self.assertLess(events.index("app.shutdown"), events.index("http.cleanup"))


if __name__ == "__main__":
    unittest.main()
