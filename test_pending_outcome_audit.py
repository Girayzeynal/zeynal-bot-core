"""Offline regression tests for read-only NBA pending-outcome audit."""
import os
import sqlite3
import tempfile
import unittest

from pending_outcome_audit import pending_outcome_audit


class PendingAuditTests(unittest.TestCase):
    def test_missing_provenance_and_eligible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "ledger.sqlite")
            with sqlite3.connect(path) as db:
                db.executescript("""
                    CREATE TABLE predictions (league TEXT, fixture_id TEXT,
                        prediction_ts_utc INTEGER, scope TEXT);
                    CREATE TABLE outcomes (league TEXT, fixture_id TEXT);
                    CREATE TABLE fixture_starts (league TEXT, fixture_id TEXT,
                        start_ts_utc INTEGER);
                    CREATE TABLE fixture_provenance (league TEXT, fixture_id TEXT,
                        provider TEXT, provider_fixture_id TEXT, start_ts_utc INTEGER);
                    INSERT INTO predictions VALUES ('NBA','knicks:bucks',100,'REGULATION_ONLY');
                    INSERT INTO predictions VALUES ('NBA','hawks:lakers',100,'REGULATION_ONLY');
                    INSERT INTO fixture_starts VALUES ('NBA','knicks:bucks',200);
                    INSERT INTO fixture_starts VALUES ('NBA','hawks:lakers',200);
                    INSERT INTO fixture_provenance VALUES ('NBA','hawks:lakers','ESPN','123',200);
                """)
            before = os.stat(path).st_mtime_ns
            report = pending_outcome_audit(path)
            self.assertEqual(report["pending"], 2)
            self.assertEqual(report["eligible_for_espn_sync"], 1)
            self.assertEqual(report["blocked"], {"MISSING_PROVENANCE": 1})
            self.assertEqual(os.stat(path).st_mtime_ns, before)

    def test_nonexistent_database_is_not_created(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "missing.sqlite")
            with self.assertRaisesRegex(ValueError, "ledger_not_found"):
                pending_outcome_audit(path)
            self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
