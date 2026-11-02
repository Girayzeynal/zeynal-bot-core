"""Regression checks for centralized persistent storage path configuration."""
import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class PersistentStoragePathTests(unittest.TestCase):
    def _tree(self, filename):
        return ast.parse((ROOT / filename).read_text(encoding="utf-8"))

    def test_main_faz23_uses_environment_path(self):
        tree = self._tree("main.py")
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "Faz23Engine"]
        self.assertTrue(calls)
        for call in calls:
            storage = next((kw.value for kw in call.keywords if kw.arg == "storage_path"), None)
            self.assertIsNotNone(storage)
            self.assertIsInstance(storage, ast.Call)
            self.assertIsInstance(storage.func, ast.Attribute)
            self.assertEqual(storage.func.attr, "getenv")
            self.assertEqual(storage.args[0].value, "FAZ23_STORAGE")

    def test_scheduler_paths_are_environment_configurable(self):
        tree = self._tree("dynamic_scheduler.py")
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name)
                 and n.func.id in {"TeamBaselineStore", "Faz23Engine"}]
        self.assertEqual({n.func.id for n in calls}, {"TeamBaselineStore", "Faz23Engine"})
        for call in calls:
            path = call.args[0] if call.args else next(
                (kw.value for kw in call.keywords if kw.arg == "storage_path"), None)
            self.assertIsInstance(path, ast.Call)
            self.assertIsInstance(path.func, ast.Attribute)
            self.assertEqual(path.func.attr, "getenv")
            self.assertEqual(path.args[0].value,
                             "BASELINE_DIR" if call.func.id == "TeamBaselineStore" else "FAZ23_STORAGE")


if __name__ == "__main__":
    unittest.main()
