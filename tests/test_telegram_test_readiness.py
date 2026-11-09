"""Safety gates for isolated Telegram testing."""
import unittest
from telegram_test_readiness import assess_telegram_test_readiness


class TelegramTestReadinessTests(unittest.TestCase):
    def setUp(self):
        self.env = {"NBA_LEDGER_ENABLED": "true",
                    "NBA_LEDGER_PATH": "/tmp/zeynal-test/ledger.sqlite"}

    def assess(self, **overrides):
        kw = dict(env=self.env, test_token_present=True,
                  isolated_storage=True, ci_passed=True)
        kw.update(overrides)
        return assess_telegram_test_readiness(**kw)

    def test_explicit_evidence_required(self):
        self.assertEqual(assess_telegram_test_readiness(env={}).status, "BLOCKED")

    def test_isolated_test_configuration_is_eligible(self):
        self.assertEqual(self.assess().status, "READY_FOR_ISOLATED_TEST")

    def test_production_volume_path_is_blocked(self):
        self.env["NBA_LEDGER_PATH"] = "/data/nba_prediction_ledger.sqlite"
        self.assertIn("PRODUCTION_LEDGER_FILENAME_NOT_ALLOWED_FOR_TEST",
                      self.assess().blockers)

    def test_production_ledger_path_traversal_is_blocked(self):
        self.env["NBA_LEDGER_PATH"] = "/data/test/../nba_prediction_ledger.sqlite"
        self.assertIn("PRODUCTION_LEDGER_FILENAME_NOT_ALLOWED_FOR_TEST",
                      self.assess().blockers)

    def test_dedicated_test_volume_path_is_eligible(self):
        self.env["NBA_LEDGER_PATH"] = "/data/test_nba_prediction_ledger.sqlite"
        self.assertEqual(self.assess().status, "READY_FOR_ISOLATED_TEST")

    def test_production_baseline_path_is_blocked(self):
        self.env["BASELINE_DIR"] = "/data/baselines"
        self.assertIn("PRODUCTION_BASELINE_PATH_NOT_ALLOWED_FOR_TEST",
                      self.assess().blockers)

    def test_production_faz23_path_is_blocked(self):
        self.env["FAZ23_STORAGE"] = "/data/faz23_storage.sqlite"
        self.assertIn("PRODUCTION_FAZ23_PATH_NOT_ALLOWED_FOR_TEST",
                      self.assess().blockers)

    def test_production_baseline_traversal_alias_is_blocked(self):
        self.env["BASELINE_DIR"] = "/data/test/../baselines"
        self.assertIn("PRODUCTION_BASELINE_PATH_NOT_ALLOWED_FOR_TEST",
                      self.assess().blockers)

    def test_production_faz23_traversal_alias_is_blocked(self):
        self.env["FAZ23_STORAGE"] = "/data/test/../faz23_storage.sqlite"
        self.assertIn("PRODUCTION_FAZ23_PATH_NOT_ALLOWED_FOR_TEST",
                      self.assess().blockers)

    def test_missing_test_token_proof_is_blocked(self):
        self.assertIn("SEPARATE_TEST_TELEGRAM_TOKEN_NOT_VERIFIED",
                      self.assess(test_token_present=False).blockers)

    def test_missing_storage_isolation_proof_is_blocked(self):
        self.assertEqual(self.assess(isolated_storage=False).status, "BLOCKED")

    def test_ci_must_be_confirmed(self):
        self.assertIn("CI_NOT_VERIFIED", self.assess(ci_passed=False).blockers)

    def test_relative_ledger_path_is_blocked(self):
        self.env["NBA_LEDGER_PATH"] = "ledger.sqlite"
        self.assertIn("TEST_LEDGER_PATH_NOT_ABSOLUTE", self.assess().blockers)


if __name__ == "__main__":
    unittest.main()
