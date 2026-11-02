"""Regression for application startup/shutdown resource ownership."""
import ast
from pathlib import Path
import unittest


class LifecycleContractTests(unittest.TestCase):
    def test_main_async_cleans_up_http_and_telegram(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8"))
        fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "main_async")
        source = ast.unparse(fn)
        self.assertIn("finally:", source)
        for required in ("runner.cleanup()", "app.shutdown()", "app.stop()", "app.updater.stop()", "scheduler_task.cancel()"):
            self.assertIn(required, source)
        self.assertIn("if initialized:", source)
        self.assertIn("if started:", source)
        self.assertIn("if polling", source)
        # Shutdown failures must not skip later cleanup operations.
        self.assertGreaterEqual(source.count("finally:"), 4)
        self.assertLess(source.index("app.updater.stop()"), source.index("app.stop()"))
        self.assertLess(source.index("app.stop()"), source.index("app.shutdown()"))
        self.assertLess(source.index("app.shutdown()"), source.index("runner.cleanup()"))

    def test_start_health_returns_runner(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8"))
        fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "start_health")
        self.assertTrue(any(isinstance(n, ast.Return) and isinstance(n.value, ast.Name) and n.value.id == "runner" for n in ast.walk(fn)))


if __name__ == "__main__":
    unittest.main()
