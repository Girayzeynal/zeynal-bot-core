import os
import tempfile
import unittest

from prediction_ledger import PredictionLedger, PredictionRecord
from providers.espn_ledger_ingest import ingest_completed_espn_nba_event


class ESPNIngestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = PredictionLedger(os.path.join(self.temp.name, "ledger.sqlite"))
        self.ledger.record_prediction(PredictionRecord(
            fixture_id="game-1", league="NBA", prediction_ts_utc=100,
            expected_home=110.0, expected_away=105.0, home_win_probability=0.6,
        ))
        self.ledger.record_fixture_start("NBA", "game-1", 150)
        self.ledger.record_fixture_provenance("NBA", "game-1", "ESPN", "espn-1", 150)

    def event(self, **changes):
        result = dict(provider="ESPN", provider_fixture_id="espn-1",
                      start_ts_utc=150, actual_home=115, actual_away=108,
                      scope="FINAL_WITH_OT")
        result.update(changes)
        return result

    def test_valid_result_idempotent(self):
        self.assertTrue(ingest_completed_espn_nba_event(
            self.ledger, "game-1", self.event(), observed_at_utc=200
        ))
        self.assertTrue(ingest_completed_espn_nba_event(
            self.ledger, "game-1", self.event(), observed_at_utc=201
        ))
        self.assertEqual(self.ledger.audit("NBA")["outcomes"], 1)

    def test_conflicting_score_rejected(self):
        self.assertTrue(ingest_completed_espn_nba_event(
            self.ledger, "game-1", self.event(), observed_at_utc=200
        ))
        self.assertFalse(ingest_completed_espn_nba_event(
            self.ledger, "game-1", self.event(actual_home=116), observed_at_utc=201
        ))

    def test_duplicate_preserves_original_result_timestamp(self):
        self.assertTrue(ingest_completed_espn_nba_event(
            self.ledger, "game-1", self.event(), observed_at_utc=200
        ))
        self.assertTrue(ingest_completed_espn_nba_event(
            self.ledger, "game-1", self.event(), observed_at_utc=300
        ))
        with self.ledger._connect() as db:
            row = db.execute(
                "SELECT result_ts_utc, actual_home, actual_away FROM outcomes "
                "WHERE league='NBA' AND fixture_id='game-1'"
            ).fetchone()
        self.assertEqual(row, (200, 115, 108))

    def test_source_id_cannot_be_reassigned_to_second_fixture(self):
        self.ledger.record_prediction(PredictionRecord(
            fixture_id="game-2", league="NBA", prediction_ts_utc=100,
            expected_home=100.0, expected_away=99.0, home_win_probability=0.5,
        ))
        self.ledger.record_fixture_start("NBA", "game-2", 150)
        self.assertFalse(self.ledger.record_fixture_provenance(
            "NBA", "game-2", "ESPN", "espn-1", 150
        ))
        self.assertFalse(ingest_completed_espn_nba_event(
            self.ledger, "game-2", self.event(), observed_at_utc=200
        ))
        self.assertEqual(self.ledger.audit("NBA")["outcomes"], 0)

    def test_result_observed_at_or_before_tipoff_rejected(self):
        for observed_at in (149, 150):
            self.assertFalse(ingest_completed_espn_nba_event(
                self.ledger, "game-1", self.event(), observed_at_utc=observed_at
            ))
        self.assertEqual(self.ledger.audit("NBA")["outcomes"], 0)

    def test_prediction_at_or_after_tipoff_rejected(self):
        for prediction_ts in (150, 151):
            with self.ledger._connect() as db:
                db.execute(
                    "UPDATE predictions SET prediction_ts_utc=? WHERE league='NBA' AND fixture_id='game-1'",
                    (prediction_ts,),
                )
            self.assertFalse(ingest_completed_espn_nba_event(
                self.ledger, "game-1", self.event(), observed_at_utc=200
            ))
        self.assertEqual(self.ledger.audit("NBA")["outcomes"], 0)

    def test_duplicate_result_rejected_if_new_observation_is_before_tipoff(self):
        self.assertTrue(ingest_completed_espn_nba_event(
            self.ledger, "game-1", self.event(), observed_at_utc=200
        ))
        self.assertFalse(ingest_completed_espn_nba_event(
            self.ledger, "game-1", self.event(), observed_at_utc=150
        ))
        with self.ledger._connect() as db:
            result = db.execute(
                "SELECT result_ts_utc, actual_home, actual_away FROM outcomes "
                "WHERE league='NBA' AND fixture_id='game-1'"
            ).fetchone()
        self.assertEqual(result, (200, 115, 108))

    def test_unmatched_fixture_rejected(self):
        self.assertFalse(ingest_completed_espn_nba_event(
            self.ledger, "wrong", self.event(), observed_at_utc=200
        ))

    def test_mismatched_source_and_start_rejected(self):
        for payload in (self.event(provider_fixture_id="wrong"),
                        self.event(start_ts_utc=151)):
            self.assertFalse(ingest_completed_espn_nba_event(
                self.ledger, "game-1", payload, observed_at_utc=200
            ))
        self.assertEqual(self.ledger.audit("NBA")["outcomes"], 0)


if __name__ == "__main__":
    unittest.main()
