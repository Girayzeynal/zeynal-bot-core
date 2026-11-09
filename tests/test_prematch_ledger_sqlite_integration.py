"""SQLite integration regressions for immutable pregame predictions.

No external API, Telegram polling, or Fly volume is required.
"""
import sqlite3
import tempfile
from pathlib import Path
import unittest

from prediction_ledger import PredictionLedger
from prematch_ledger_bridge import record_verified_prematch_projection


class PrematchLedgerSQLiteIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "nba.sqlite"
        self.ledger = PredictionLedger(str(self.path))
        self.kw = dict(
            league="NBA", fixture_id="401999001", provider="ESPN",
            provider_fixture_id="401999001", tipoff_utc=200000,
            prediction_utc=190000, expected_home=111.5, expected_away=109.5,
        )

    def read_rows(self):
        with sqlite3.connect(self.path) as db:
            return db.execute(
                "SELECT prediction_ts_utc, expected_home, expected_away "
                "FROM predictions WHERE league='NBA' AND fixture_id='401999001'"
            ).fetchall()

    def test_first_insert_persists_after_reopening_database(self):
        self.assertTrue(record_verified_prematch_projection(self.ledger, **self.kw))
        self.assertEqual(self.read_rows(), [(190000, 111.5, 109.5)])
        reopened = PredictionLedger(str(self.path))
        with reopened._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM predictions").fetchone()[0], 1)

    def test_identical_retry_is_not_a_new_forecast(self):
        self.assertTrue(record_verified_prematch_projection(self.ledger, **self.kw))
        self.assertFalse(record_verified_prematch_projection(self.ledger, **self.kw))
        self.assertEqual(len(self.read_rows()), 1)

    def test_conflicting_retry_does_not_overwrite_original(self):
        self.assertTrue(record_verified_prematch_projection(self.ledger, **self.kw))
        with self.assertRaises(ValueError):
            record_verified_prematch_projection(
                self.ledger, **(self.kw | {"expected_home": 120.0}))
        self.assertEqual(self.read_rows(), [(190000, 111.5, 109.5)])

    def test_provider_identity_collision_rolls_back(self):
        self.assertTrue(record_verified_prematch_projection(self.ledger, **self.kw))
        with self.assertRaises(ValueError):
            record_verified_prematch_projection(
                self.ledger, **(self.kw | {"fixture_id": "401999002"}))
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM predictions").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM fixture_starts").fetchone()[0], 1)

    def test_prediction_after_tipoff_is_rejected_without_writes(self):
        with self.assertRaises(ValueError):
            record_verified_prematch_projection(
                self.ledger, **(self.kw | {"prediction_utc": 200000}))
        self.assertEqual(self.read_rows(), [])

    def test_conflicting_tipoff_rolls_back(self):
        self.assertTrue(record_verified_prematch_projection(self.ledger, **self.kw))
        with self.assertRaises(ValueError):
            record_verified_prematch_projection(
                self.ledger, **(self.kw | {"tipoff_utc": 210000}))
        self.assertEqual(self.read_rows(), [(190000, 111.5, 109.5)])


if __name__ == "__main__":
    unittest.main()
