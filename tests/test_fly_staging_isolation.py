"""Static staging deployment isolation invariants; no Fly API calls."""
from pathlib import Path
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FlyStagingIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prod = tomllib.loads((ROOT / "fly.toml").read_text())
        cls.stage = tomllib.loads((ROOT / "fly.staging.toml").read_text())

    def test_staging_app_is_not_production(self):
        self.assertNotEqual(self.prod["app"], self.stage["app"])

    def test_staging_volume_is_not_production(self):
        self.assertNotEqual(self.prod["mounts"]["source"],
                            self.stage["mounts"]["source"])

    def test_all_stateful_paths_are_isolated(self):
        for name in ("BASELINE_DIR", "FAZ23_STORAGE", "SCHEDULER_DB", "NBA_LEDGER_PATH"):
            self.assertNotEqual(self.prod["env"][name], self.stage["env"][name])
            self.assertTrue(self.stage["env"][name].startswith("/data/test_"))

    def test_staging_ledger_enabled_and_ready_health_check(self):
        self.assertEqual(self.stage["env"]["NBA_LEDGER_ENABLED"], "true")
        self.assertEqual(self.stage["http_service"]["checks"][0]["path"], "/ready")

    def test_staging_has_no_inline_secrets(self):
        for key in self.stage["env"]:
            self.assertNotIn("TOKEN", key)
            self.assertNotIn("SECRET", key)
            self.assertNotIn("API_SPORTS_KEY", key)


if __name__ == "__main__":
    unittest.main()
