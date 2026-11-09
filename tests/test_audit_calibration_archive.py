"""CLI regression tests: existing database is never created or mutated."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from audit_calibration_archive import run
from prediction_ledger import PredictionLedger, PredictionRecord, OutcomeRecord


class ArchiveCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "ledger.sqlite"

    def test_missing_file_is_not_created(self):
        with self.assertRaises(FileNotFoundError):
            run(str(self.path))
        self.assertFalse(self.path.exists())

    def test_read_only_report_does_not_modify_archive(self):
        ledger = PredictionLedger(str(self.path))
        ledger.record_prediction(PredictionRecord("g1", "NBA", 100, 100, 100, None))
        ledger.record_outcome(OutcomeRecord("g1", "NBA", 300, 100, 100))
        before = self.path.read_bytes()
        report = run(str(self.path))
        self.assertEqual(report["predictions"], 1)
        self.assertEqual(report["eligible_count"], 0)
        self.assertEqual(report["excluded"]["missing_tipoff"], 1)
        self.assertEqual(self.path.read_bytes(), before)

    def test_non_ledger_sqlite_rejected(self):
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE other (x INTEGER)")
        with self.assertRaisesRegex(ValueError, "missing required tables"):
            run(str(self.path))


if __name__ == "__main__":
    unittest.main()
