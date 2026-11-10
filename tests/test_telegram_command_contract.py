"""Offline Telegram command contract checks; NOT a live Telegram test.

These tests deliberately avoid network access and bot tokens. They prevent
missing handlers or silent early-return branches from passing CI unnoticed.
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))


def function(name):
    matches = [n for n in SOURCE.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name]
    assert len(matches) == 1, f"Missing async handler: {name}"
    return matches[0]


class TelegramCommandContractTests(unittest.TestCase):
    def test_required_handlers_are_registered(self):
        expected = {
            "start": "start_command",
            "nba": "nba_command",
            "analyze": "analyze_command",
            "compare": "compare_command",
            "accuracy": "accuracy_command",
            "auditstatus": "auditstatus_command",
        }
        registrations = {}
        for node in ast.walk(SOURCE):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id != "CommandHandler" or len(node.args) < 2:
                continue
            if isinstance(node.args[0], ast.Constant) and isinstance(node.args[1], ast.Name):
                registrations[node.args[0].value] = node.args[1].id
        for command, handler in expected.items():
            with self.subTest(command=command):
                self.assertEqual(registrations.get(command), handler)
                function(handler)

    def test_compare_replies_on_invalid_input_and_missing_ledger(self):
        node = function("compare_command")
        replies = [n for n in ast.walk(node) if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Attribute) and n.func.attr == "reply_text"]
        self.assertGreaterEqual(len(replies), 2)
        literal_text = " ".join(n.value for n in ast.walk(node)
                                if isinstance(n, ast.Constant) and isinstance(n.value, str))
        self.assertIn("Kullanım: /compare NBA ESPN_MAC_ID", literal_text)
        self.assertIn("arşivi etkin değil", literal_text)

    def test_accuracy_replies_when_archive_is_disabled(self):
        node = function("accuracy_command")
        literal_text = " ".join(n.value for n in ast.walk(node)
                                if isinstance(n, ast.Constant) and isinstance(n.value, str))
        self.assertIn("arşiv etkin değil", literal_text)
        self.assertTrue(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                            and n.func.attr == "reply_text" for n in ast.walk(node)))

    def test_start_help_mentions_comparison_and_accuracy(self):
        node = function("start_command")
        literal_text = " ".join(n.value for n in ast.walk(node)
                                if isinstance(n, ast.Constant) and isinstance(n.value, str))
        self.assertIn("/compare NBA ESPN_MAC_ID", literal_text)
        self.assertIn("/accuracy", literal_text)


if __name__ == "__main__":
    unittest.main()
