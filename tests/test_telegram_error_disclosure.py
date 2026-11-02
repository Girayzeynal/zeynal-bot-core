"""Static regression: Telegram must not receive internal analysis exceptions."""
import ast
from pathlib import Path
import unittest


class TelegramErrorDisclosureTests(unittest.TestCase):
    def test_analyze_does_not_send_exception_details(self):
        source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        analyze = next(
            node for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "analyze_command"
        )
        handlers = [
            node for node in ast.walk(analyze)
            if isinstance(node, ast.ExceptHandler) and node.type is not None
            and isinstance(node.type, ast.Name) and node.type.id == "Exception"
        ]
        self.assertTrue(handlers)
        for handler in handlers:
            for node in ast.walk(handler):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "reply_text":
                    self.assertTrue(node.args)
                    self.assertIsInstance(node.args[0], ast.Constant)
                    self.assertIsInstance(node.args[0].value, str)


if __name__ == "__main__":
    unittest.main()
