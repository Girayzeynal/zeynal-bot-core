"""Ensure estimated ESPN pace remains explicit and fail-closed by default."""
import ast
from pathlib import Path
import unittest


class EspnPaceConfigTests(unittest.TestCase):
    def test_bootstrapper_uses_explicit_opt_in(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8"))
        build = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "build_app")
        assignments = [node for node in ast.walk(build) if isinstance(node, ast.Assign)]
        configured = [node for node in assignments if any(isinstance(t, ast.Name) and t.id == "espn_estimated_pace" for t in node.targets)]
        self.assertEqual(len(configured), 1)
        self.assertIn('"false"', ast.unparse(configured[0]).lower())
        calls = [node for node in ast.walk(build) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ESPNAdapter"]
        self.assertTrue(any(any(kw.arg == "allow_estimated_pace" and isinstance(kw.value, ast.Name) and kw.value.id == "espn_estimated_pace" for kw in call.keywords) for call in calls))


if __name__ == "__main__":
    unittest.main()
