"""Test actual bot construction with all external services mocked.

No Telegram network access, Fly volume, or ESPN calls are needed.
"""
import ast
import logging
import os
import pathlib
import tempfile
import types
import unittest
from unittest.mock import patch


def load_build_app(namespace):
    path = pathlib.Path(__file__).resolve().parents[1] / "main.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
             and n.name == "build_app"]
    assert len(nodes) == 1
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
                 str(path), "exec"), namespace)
    return namespace["build_app"]


class FakeApplication:
    def __init__(self):
        self.bot_data = {}
        self.handlers = []

    @classmethod
    def builder(cls):
        return types.SimpleNamespace(token=lambda token: types.SimpleNamespace(
            build=lambda: cls()))

    def add_handler(self, handler):
        self.handlers.append(handler)


class BotLedgerStartupTests(unittest.TestCase):
    def make_builder(self):
        class FakeLedger:
            def __init__(self, path):
                self.path = path

        namespace = {
            "Application": FakeApplication,
            "TELEGRAM_BOT_TOKEN": "dummy",
            "API_SPORTS_KEY": "dummy",
            "API_SPORTS_BASE": "dummy",
            "TeamBaselineStore": lambda **kw: object(),
            "TeamBaselineBootstrapper": lambda **kw: object(),
            "Faz13Engine": lambda **kw: object(),
            "Faz22Engine": lambda: object(),
            "Faz23Engine": lambda **kw: object(),
            "ESPNAdapter": lambda **kwargs: object(),
            "PredictionLedger": FakeLedger,
            "resolve_prediction_ledger_path": __import__(
                "ledger_storage_config").resolve_prediction_ledger_path,
            "CommandHandler": lambda *args: args,
            "start_command": object(), "analyze_command": object(),
            "nba_command": object(), "compare_command": object(),
            "newscheck_command": object(), "auditstatus_command": object(),
            "accuracy_command": object(),
            "logger": logging.getLogger("startup-test"),
            "os": os,
        }
        return load_build_app(namespace)

    def test_disabled_does_not_construct_ledger(self):
        builder = self.make_builder()
        with patch.dict(os.environ, {"NBA_LEDGER_ENABLED": "false"}, clear=False):
            app = builder()
        self.assertNotIn("nba_prediction_ledger", app.bot_data)
        self.assertNotIn("nba_espn_adapter", app.bot_data)
        self.assertEqual(len(app.handlers), 7)

    def test_newscheck_handler_registered_without_ledger(self):
        builder = self.make_builder()
        with patch.dict(os.environ, {"NBA_LEDGER_ENABLED": "false"}, clear=False):
            app = builder()
        commands = [handler[0] for handler in app.handlers]
        self.assertEqual(commands, ["start", "analyze", "nba", "compare", "auditstatus", "accuracy", "newscheck"])
        self.assertNotIn("nba_prediction_ledger", app.bot_data)

    def test_enabled_constructs_ledger_on_volume(self):
        builder = self.make_builder()
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "ledger.sqlite")
            from ledger_storage_config import resolve_prediction_ledger_path
            def local_resolver(*, enabled, configured_path):
                return resolve_prediction_ledger_path(
                    enabled=enabled, configured_path=configured_path,
                    volume_root=root)
            builder.__globals__["resolve_prediction_ledger_path"] = local_resolver
            with patch.dict(os.environ, {"NBA_LEDGER_ENABLED": "true",
                                          "NBA_LEDGER_PATH": path}):
                app = builder()
            self.assertEqual(app.bot_data["nba_prediction_ledger"].path, path)
            self.assertIn("nba_espn_adapter", app.bot_data)

    def test_enabled_rejects_unmounted_volume(self):
        builder = self.make_builder()
        with patch.dict(os.environ, {"NBA_LEDGER_ENABLED": "true",
                                      "NBA_LEDGER_PATH": "/data/ledger.sqlite"}):
            with self.assertRaises((FileNotFoundError, RuntimeError)):
                builder()


if __name__ == "__main__":
    unittest.main()
