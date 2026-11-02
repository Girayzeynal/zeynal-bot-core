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


    def test_sqlite_writers_create_parent_directories(self):
        for filename in ("dynamic_scheduler.py", "faz23_engine/faz23_engine.py"):
            with self.subTest(filename=filename):
                tree = self._tree(filename)
                mkdir_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                               and isinstance(n.func, ast.Attribute)
                               and n.func.attr == "mkdir"]
                self.assertTrue(mkdir_calls, "Missing SQLite parent directory creation")
                self.assertTrue(any(
                    any(kw.arg == "parents" and isinstance(kw.value, ast.Constant)
                        and kw.value.value is True for kw in call.keywords)
                    for call in mkdir_calls
                ))

    def test_faz23_creates_nested_database_and_can_reopen(self):
        import tempfile
        from faz23_engine.faz23_engine import Faz23Engine

        with tempfile.TemporaryDirectory() as directory:
            db_path = pathlib.Path(directory) / "nested" / "state" / "faz23.sqlite"
            self.assertFalse(db_path.parent.exists())
            Faz23Engine(storage_path=str(db_path))
            self.assertTrue(db_path.is_file())
            Faz23Engine(storage_path=str(db_path))

    def test_scheduler_creates_nested_database(self):
        import tempfile
        from unittest.mock import patch
        import dynamic_scheduler

        with tempfile.TemporaryDirectory() as directory:
            db_path = pathlib.Path(directory) / "nested" / "state" / "scheduler.sqlite"
            self.assertFalse(db_path.parent.exists())
            with patch.object(dynamic_scheduler, "DB_PATH", str(db_path)):
                dynamic_scheduler.init_db()
            self.assertTrue(db_path.is_file())

if __name__ == "__main__":
    unittest.main()
