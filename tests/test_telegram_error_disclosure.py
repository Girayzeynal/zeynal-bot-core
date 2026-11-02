"""Regression: internal analysis exceptions must not be sent to Telegram."""
import ast
from pathlib import Path
import unittest


class TelegramErrorDisclosureTests(unittest.TestCase):
    def test_internal_analyze_exception_is_not_disclosed(self):
        source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        analyze = next(
            node for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "analyze_command"
        )
        handlers = [
            node for node in ast.walk(analyze)
            if isinstance(node, ast.ExceptHandler)
            and isinstance(node.type, ast.Name) and node.type.id == "Exception"
        ]
        self.assertGreaterEqual(len(handlers), 2)
        internal_handler = handlers[-1]
        replies = [
            node for node in ast.walk(internal_handler)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "reply_text"
        ]
        self.assertEqual(len(replies), 1)
        self.assertTrue(replies[0].args)
        self.assertIsInstance(replies[0].args[0], ast.Constant)
        self.assertIsInstance(replies[0].args[0].value, str)


if __name__ == "__main__":
    unittest.main()
