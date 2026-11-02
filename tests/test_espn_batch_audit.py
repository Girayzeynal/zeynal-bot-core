import os
import tempfile
import unittest

from prediction_ledger import PredictionLedger, PredictionRecord
from providers.espn_batch_audit import ingest_espn_batch


def event(source="espn-1", completed=True):
    return {
        "id": source,
        "date": "2025-10-25T23:00:00Z",
        "competitions": [{
            "status": {"type": {
                "state": "completed" if completed else "in",
                "completed": completed,
            }},
            "competitors": [
                {"homeAway": "home", "team": {"id": "1"}, "score": "115"},
                {"homeAway": "away", "team": {"id": "2"}, "score": "108"},
            ],
        }],
    }


class ESPNBatchAuditTests(unittest.TestCase):
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

    def test_mixed_batch_counts_all_dispositions(self):
        items = [
            {"fixture_id": "local-1", "event": event()},
            {"fixture_id": "local-1", "event": event(completed=False)},
            {"fixture_id": "local-1", "event": event(source="wrong")},
            {"fixture_id": "local-1", "event": None},
        ]
        report = ingest_espn_batch(self.ledger, items, self.start + 7200)
        self.assertEqual(report["total"], 4)
        self.assertEqual(report["accepted"], 1)
        self.assertEqual(report["rejected"], 3)
        self.assertAlmostEqual(report["acceptance_rate"], 0.25)
        self.assertEqual(report["statuses"]["invalid_input"], 1)
        self.assertEqual(report["statuses"]["invalid_or_incomplete_event"], 1)
        self.assertEqual(report["statuses"]["unmatched_or_conflicting_fixture"], 1)
        self.assertEqual(report["ledger_audit"]["provider_consistent_prematch_pairs"], 1)

    def test_empty_batch_has_no_misleading_rate(self):
        report = ingest_espn_batch(self.ledger, [], self.start + 7200)
        self.assertEqual(report["total"], 0)
        self.assertIsNone(report["acceptance_rate"])


if __name__ == "__main__":
    unittest.main()
