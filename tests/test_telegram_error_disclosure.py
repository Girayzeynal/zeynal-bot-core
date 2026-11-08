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
        # New fixture-provider handlers may follow the internal analysis handler
        # in AST traversal; identify the internal handler by its fixed message.
        internal_replies = []
        for handler in handlers:
            for node in ast.walk(handler):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "reply_text"
                        and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)
                        and "dahili bir hata" in node.args[0].value):
                    internal_replies.append(node)
        self.assertEqual(len(internal_replies), 1)
        self.assertNotIn("str(e)", internal_replies[0].args[0].value)


if __name__ == "__main__":
    unittest.main()
