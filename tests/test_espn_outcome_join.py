import os
import sqlite3
import tempfile
import unittest
from espn_outcome_join import import_verified_espn_outcome
from prediction_ledger import PredictionLedger, PredictionRecord


def event(ot=False):
    home = [25, 25, 25, 25] + ([12] if ot else [])
    away = [24, 24, 24, 28] + ([12] if ot else [])
    return {"id": "espn-1", "status": {"type": {"completed": True, "name": "STATUS_FINAL"}},
            "competitions": [{"competitors": [
                {"homeAway": "home", "score": str(sum(home)), "linescores": [{"value": x} for x in home]},
                {"homeAway": "away", "score": str(sum(away)), "linescores": [{"value": x} for x in away]},
            ]}]}


class VerifiedOutcomeJoinTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "ledger.sqlite")
        ledger = PredictionLedger(self.path)
        ledger.record_prediction(PredictionRecord(
            league="NBA", fixture_id="fixture-1", prediction_ts_utc=100,
            expected_home=102.0, expected_away=99.0, home_win_probability=0.5, scope="REGULATION_ONLY",
        ))
        ledger.record_fixture_start("NBA", "fixture-1", 200)
        ledger.record_fixture_provenance("NBA", "fixture-1", "ESPN", "espn-1", 200)

    def test_verified_overtime_import_and_idempotence(self):
        first = import_verified_espn_outcome(self.path, event(True), 300)
        self.assertEqual(first["status"], "IMPORTED")
        self.assertTrue(first["has_overtime"])
        self.assertEqual(import_verified_espn_outcome(self.path, event(True), 301)["status"], "ALREADY_RECORDED")
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT actual_home, actual_away, scope FROM outcomes").fetchone(),
                             (100, 100, "REGULATION_ONLY"))

    def test_unmatched_provider_rejected(self):
        bad = event()
        bad["id"] = "other"
        self.assertEqual(import_verified_espn_outcome(self.path, bad, 300)["status"], "NO_UNIQUE_MATCH")

    def test_before_tipoff_rejected(self):
        self.assertEqual(import_verified_espn_outcome(self.path, event(), 199)["status"], "REJECTED_TIME")

    def test_live_rejected(self):
        bad = event()
        bad["status"]["type"]["completed"] = False
        self.assertEqual(import_verified_espn_outcome(self.path, bad, 300)["status"], "REJECTED_FINAL")


if __name__ == "__main__":
    unittest.main()
