import contextlib
import io
import json
import os
import tempfile
import unittest

from prediction_ledger import PredictionLedger
from verified_backtest_cli import main


class VerifiedBacktestCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "ledger.sqlite")

    def run_cli(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(list(args))
        return code, json.loads(output.getvalue())

    def test_missing_file_does_not_create_database(self):
        code, result = self.run_cli(self.path)
        self.assertEqual(code, 2)
        self.assertEqual(result["reason"], "database_not_found")
        self.assertFalse(os.path.exists(self.path))

    def test_existing_ledger_without_provenance_tables_rejected(self):
        PredictionLedger(self.path)
        code, result = self.run_cli(self.path)
        self.assertEqual(code, 2)
        self.assertEqual(result["reason"], "missing_ledger_tables")

    def test_empty_verified_ledger_has_no_metrics(self):
        ledger = PredictionLedger(self.path)
        ledger.record_fixture_start("NBA", "seed", 200)
        ledger.record_fixture_provenance("NBA", "seed", "ESPN", "source-seed", 200)
        before = os.stat(self.path).st_mtime_ns
        code, result = self.run_cli(self.path)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "no_verified_pairs")
        self.assertIsNone(result["metrics"])
        self.assertEqual(os.stat(self.path).st_mtime_ns, before)


if __name__ == "__main__":
    unittest.main()
