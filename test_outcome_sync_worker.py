"""Tests for bounded verified outcome sync worker; never contact ESPN."""
import os
import tempfile
import unittest
from unittest.mock import patch

import outcome_sync_worker


class WorkerTests(unittest.TestCase):
    def test_dry_run_and_interval(self):
        with tempfile.NamedTemporaryFile() as db:
            with patch.object(outcome_sync_worker, "run", return_value={"mode": "dry_run", "scanned": 0, "results": []}) as sync:
                waits = []
                reports = outcome_sync_worker.execute(db.name, cycles=3, interval_seconds=60, sleep=waits.append)
            self.assertEqual(len(reports), 3)
            self.assertEqual(waits, [60, 60])
            self.assertEqual(sync.call_count, 3)
            sync.assert_any_call(db.name, apply=False, limit=20)

    def test_missing_database_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(outcome_sync_worker, "run") as sync:
                with self.assertRaisesRegex(ValueError, "ledger_not_found"):
                    outcome_sync_worker.execute(os.path.join(directory, "missing.sqlite"), apply=True)
                sync.assert_not_called()

    def test_provider_denial_exits_nonzero(self):
        with tempfile.NamedTemporaryFile() as db:
            with patch.object(outcome_sync_worker, "run", return_value={
                "mode": "dry_run", "scanned": 1,
                "results": [{"event_id": "401909960", "status": "PROVIDER_ACCESS_DENIED"}]
            }):
                code = outcome_sync_worker.main([db.name])
            self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
