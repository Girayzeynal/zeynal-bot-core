import os
import tempfile
import unittest
from unittest.mock import patch
from ledger_readiness import ledger_readiness
from prediction_ledger import PredictionLedger


class LedgerReadinessTests(unittest.TestCase):
    def test_no_volume_fails_closed(self):
        with patch("ledger_readiness.os.path.ismount", return_value=False):
            result = ledger_readiness()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "persistent_volume_not_mounted")

    def test_existing_volume_without_db_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            with patch("ledger_readiness.os.path.ismount", return_value=True):
                result = ledger_readiness(os.path.join(root, "missing.sqlite"), root)
        self.assertEqual(result["reason"], "database_not_found")

    def test_existing_database_read_only(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "ledger.sqlite")
            ledger = PredictionLedger(path)
            ledger.record_fixture_start("NBA", "one", 200)
            ledger.record_fixture_provenance("NBA", "one", "ESPN", "401999999", 200)
            with patch("ledger_readiness.os.path.ismount", return_value=True):
                result = ledger_readiness(path, root)
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["prediction_count"], 0)
            self.assertEqual(result["espn_provenance_count"], 1)


if __name__ == "__main__":
    unittest.main()
