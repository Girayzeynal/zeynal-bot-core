import os
import tempfile
import unittest
from types import SimpleNamespace

from prediction_ledger import PredictionLedger
from prematch_ledger_bridge import record_verified_prematch_projection, record_faz13_verified_projection


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

    def test_faz13_projection_bridge_records_explicit_team_scores(self):
        core = SimpleNamespace(
            ctx=SimpleNamespace(league="NBA"),
            meta={"data_quality": "VERIFIED_BASELINE", "generated_at": 100,
                  "expected_home": 110.0, "expected_away": 105.0,
                  "expected_total": 215.0},
        )
        self.assertTrue(record_faz13_verified_projection(
            self.ledger, core, fixture_id="game-1",
            provider_fixture_id="espn-1", tipoff_utc=200))
        with self.ledger._connect() as db:
            self.assertEqual(db.execute(
                "SELECT expected_home, expected_away FROM predictions"
            ).fetchone(), (110.0, 105.0))

    def test_faz13_bridge_rejects_manual_and_inconsistent_scores(self):
        core = SimpleNamespace(
            ctx=SimpleNamespace(league="NBA"),
            meta={"data_quality": "MANUAL_BASELINE", "generated_at": 100,
                  "expected_home": 110.0, "expected_away": 105.0,
                  "expected_total": 215.0},
        )
        args = dict(fixture_id="game-1", provider_fixture_id="espn-1", tipoff_utc=200)
        with self.assertRaises(ValueError):
            record_faz13_verified_projection(self.ledger, core, **args)
        core.meta["data_quality"] = "VERIFIED_BASELINE"
        core.meta["expected_total"] = 250.0
        with self.assertRaises(ValueError):
            record_faz13_verified_projection(self.ledger, core, **args)
        with self.ledger._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM predictions").fetchone()[0], 0)

    def test_rejects_unverified_provider(self):
        with self.assertRaises(ValueError):
            record_verified_prematch_projection(
                self.ledger, **{**self.kwargs, "provider": "UNVERIFIED"})


if __name__ == "__main__":
    unittest.main()
