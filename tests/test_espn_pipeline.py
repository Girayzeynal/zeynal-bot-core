import os
import tempfile
import unittest

from prediction_ledger import PredictionLedger, PredictionRecord
from providers.espn_pipeline import ingest_espn_payload


def event(source_id="espn-1", complete=True, home_score="115"):
    return {
        "id": source_id,
        "date": "2025-10-25T23:00:00Z",
        "competitions": [{
            "status": {"type": {"state": "completed" if complete else "in",
                                 "completed": complete}},
            "competitors": [
                {"homeAway": "home", "team": {"id": "1"}, "score": home_score},
                {"homeAway": "away", "team": {"id": "2"}, "score": "108"},
            ],
        }],
    }


class ESPNEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = PredictionLedger(os.path.join(self.temp.name, "db.sqlite"))
        self.start = 1761433200
        self.ledger.record_prediction(PredictionRecord(
            fixture_id="local-1", league="NBA",
            prediction_ts_utc=self.start - 3600,
            expected_home=110.0, expected_away=105.0,
            home_win_probability=0.6,
        ))
        self.ledger.record_fixture_start("NBA", "local-1", self.start)
        self.ledger.record_fixture_provenance(
            "NBA", "local-1", "ESPN", "espn-1", self.start
        )

    def test_valid_payload_ingests_and_evaluates(self):
        status = ingest_espn_payload(
            self.ledger, "local-1", event(), self.start + 7200
        )
        self.assertEqual(status, "accepted")
        self.assertEqual(self.ledger.audit_provenance("NBA")["provider_consistent_prematch_pairs"], 1)
        self.assertEqual(self.ledger.evaluate_provenance_verified("NBA").n_games, 1)

    def test_incomplete_payload_rejected(self):
        self.assertEqual(ingest_espn_payload(
            self.ledger, "local-1", event(complete=False), self.start + 7200
        ), "invalid_or_incomplete_event")
        self.assertEqual(self.ledger.audit("NBA")["outcomes"], 0)

    def test_wrong_source_identity_rejected(self):
        self.assertEqual(ingest_espn_payload(
            self.ledger, "local-1", event(source_id="wrong"), self.start + 7200
        ), "unmatched_or_conflicting_fixture")

    def test_conflicting_duplicate_rejected(self):
        self.assertEqual(ingest_espn_payload(
            self.ledger, "local-1", event(), self.start + 7200
        ), "accepted")
        self.assertEqual(ingest_espn_payload(
            self.ledger, "local-1", event(home_score="116"), self.start + 8000
        ), "unmatched_or_conflicting_fixture")


if __name__ == "__main__":
    unittest.main()
