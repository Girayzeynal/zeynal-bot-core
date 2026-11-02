"""Static readiness contract regression."""
import ast
from pathlib import Path
import unittest


class ReadinessContractTests(unittest.TestCase):
    def test_health_and_ready_routes_are_separate(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8"))
        fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "start_health")
        routes = [
            n.args[0].value for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "add_get" and n.args and isinstance(n.args[0], ast.Constant)
        ]
        self.assertIn("/health", routes)
        self.assertIn("/ready", routes)
        ready = next(n for n in fn.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "ready")
        self.assertIn("503", ast.unparse(ready))
        self.assertIn("updater.running", ast.unparse(ready))


if __name__ == "__main__":
    unittest.main()
