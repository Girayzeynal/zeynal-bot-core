import os
import tempfile
import unittest
from unittest.mock import patch
from prediction_ledger import PredictionLedger, PredictionRecord
from espn_outcome_sync import eligible_espn_ids, run


class ESPNOutcomeSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = os.path.join(self.temp.name, "ledger.sqlite")
        ledger = PredictionLedger(self.path)
        ledger.record_prediction(PredictionRecord(
            fixture_id="one", league="NBA", prediction_ts_utc=100,
            expected_home=101, expected_away=99, home_win_probability=0.5,
            scope="REGULATION_ONLY"))
        ledger.record_fixture_start("NBA", "one", 200)
        ledger.record_fixture_provenance("NBA", "one", "ESPN", "401999999", 200)

    def test_only_eligible_ids(self):
        self.assertEqual(eligible_espn_ids(self.path), ["401999999"])

    def test_dry_run_never_writes(self):
        event = {"id": "401999999", "status": {"type": {"completed": True, "name": "STATUS_FINAL"}},
                 "competitions": [{"competitors": [
                     {"homeAway": "home", "score": "100", "linescores": [{"value": 25}] * 4},
                     {"homeAway": "away", "score": "96", "linescores": [{"value": 24}] * 4},
                 ]}]}
        with patch("espn_outcome_sync.fetch_espn_event", return_value=event):
            result = run(self.path)
        self.assertEqual(result["results"][0]["status"], "VERIFIED_DRY_RUN")
        self.assertEqual(eligible_espn_ids(self.path), ["401999999"])

    def test_missing_ledger_rejected_without_creating(self):
        missing = self.path + ".missing"
        with self.assertRaises(ValueError):
            eligible_espn_ids(missing)
        self.assertFalse(os.path.exists(missing))


if __name__ == "__main__":
    unittest.main()
