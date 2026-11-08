"""Regression tests for pasted quotation marks in /analyze commands."""
import ast
from pathlib import Path
import unittest


source = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(encoding="utf-8")
module = ast.parse(source)
parser = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "parse_analyze")
namespace = {"Tuple": tuple, "datetime": __import__("datetime").datetime}
exec(compile(ast.Module(body=[parser], type_ignores=[]), "<parser>", "exec"), namespace)


class TestAnalyzeTeamQuotes(unittest.TestCase):
    def test_trailing_quote(self):
        result = namespace["parse_analyze"]('/analyze NBA 2026-11-10 Houston Rockets vs Denver Nuggets"')
        self.assertEqual(result[2:], ("Houston Rockets", "Denver Nuggets"))

    def test_curly_quotes(self):
        result = namespace["parse_analyze"]('/analyze NBA 2026-11-10 “Houston Rockets” vs “Denver Nuggets”')
        self.assertEqual(result[2:], ("Houston Rockets", "Denver Nuggets"))

    def test_missing_team_still_rejected(self):
        with self.assertRaises(ValueError):
            namespace["parse_analyze"]('/analyze NBA 2026-11-10 Houston Rockets vs " "')


if __name__ == "__main__":
    unittest.main()
