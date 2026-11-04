import os
import tempfile
import unittest

from prediction_ledger import PredictionLedger
from prematch_ledger_bridge import record_verified_prematch_projection


class PrematchLedgerBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = PredictionLedger(os.path.join(self.tmp.name, "ledger.sqlite"))
        self.kwargs = dict(
            league="NBA", fixture_id="game-1", provider="ESPN",
            provider_fixture_id="espn-1", tipoff_utc=200,
            prediction_utc=100, expected_home=110.0, expected_away=105.0,
        )

    def test_atomic_insert_and_idempotency(self):
        self.assertTrue(record_verified_prematch_projection(self.ledger, **self.kwargs))
        self.assertFalse(record_verified_prematch_projection(self.ledger, **self.kwargs))
        with self.ledger._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM predictions").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM fixture_provenance").fetchone()[0], 1)

    def test_rejects_at_tipoff_without_writes(self):
        with self.assertRaises(ValueError):
            record_verified_prematch_projection(self.ledger, **{**self.kwargs, "prediction_utc": 200})
        with self.ledger._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM predictions").fetchone()[0], 0)

    def test_conflicting_identity_does_not_partially_insert(self):
        record_verified_prematch_projection(self.ledger, **self.kwargs)
        with self.assertRaises(ValueError):
            record_verified_prematch_projection(
                self.ledger, **{**self.kwargs, "fixture_id": "game-2"})
        with self.ledger._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM predictions").fetchone()[0], 1)

    def test_conflicting_projection_cannot_replace_original(self):
        record_verified_prematch_projection(self.ledger, **self.kwargs)
        with self.assertRaises(ValueError):
            record_verified_prematch_projection(
                self.ledger, **{**self.kwargs, "expected_home": 120.0})

    def test_rejects_unverified_provider(self):
        with self.assertRaises(ValueError):
            record_verified_prematch_projection(
                self.ledger, **{**self.kwargs, "provider": "UNVERIFIED"})


if __name__ == "__main__":
    unittest.main()
