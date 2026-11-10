import sqlite3
import tempfile
import unittest
from pathlib import Path

from ledger_operational_status import ledger_operational_status
from prediction_ledger import PredictionLedger, PredictionRecord, OutcomeRecord


class OperationalStatusTests(unittest.TestCase):
    def test_disabled_and_missing_fail_closed(self):
        self.assertEqual(ledger_operational_status(None)["status"], "DISABLED")
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(ledger_operational_status(str(Path(folder) / "absent.db"))["status"], "MISSING")
            self.assertFalse((Path(folder) / "absent.db").exists())

    def test_empty_and_paired_counts_do_not_claim_calibration(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "ledger.db")
            ledger = PredictionLedger(path)
            empty = ledger_operational_status(path)
            self.assertEqual((empty["predictions"], empty["outcomes"], empty["paired"]), (0, 0, 0))
            ledger.record_prediction(PredictionRecord("game1", "NBA", 100, 105, 103, None))
            ledger.record_outcome(OutcomeRecord("game1", "NBA", 200, 101, 102))
            self.assertEqual(ledger_operational_status(path)["paired"], 0)
            ledger.record_fixture_start("NBA", "game1", 150)
            result = ledger_operational_status(path)
            self.assertEqual((result["predictions"], result["outcomes"], result["paired"]), (1, 1, 1))
            self.assertEqual(result["calibration"], "NOT_VERIFIED")

    def test_rejects_post_tipoff_prediction_and_scope_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "ledger.db")
            ledger = PredictionLedger(path)
            ledger.record_prediction(PredictionRecord(
                "late", "NBA", 160, 100, 99, None))
            ledger.record_fixture_start("NBA", "late", 150)
            ledger.record_outcome(OutcomeRecord(
                "late", "NBA", 200, 101, 102))
            ledger.record_prediction(PredictionRecord(
                "scope", "NBA", 100, 100, 99, None,
                scope="REGULATION_ONLY"))
            ledger.record_fixture_start("NBA", "scope", 150)
            ledger.record_outcome(OutcomeRecord(
                "scope", "NBA", 200, 101, 102,
                scope="FINAL_WITH_OT"))
            status = ledger_operational_status(path)
            self.assertEqual(status["predictions"], 2)
            self.assertEqual(status["outcomes"], 2)
            self.assertEqual(status["paired"], 0)
            self.assertEqual(status["calibration"], "NOT_VERIFIED")

    def test_incomplete_schema(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "empty.db")
            with sqlite3.connect(path):
                pass
            self.assertEqual(ledger_operational_status(path)["status"], "INCOMPLETE")


if __name__ == "__main__":
    unittest.main()
