import copy
import unittest
from providers.espn_scheduled_fixture import parse_scheduled_nba_fixture


def event():
    return {
        "id": "401999001", "date": "2026-11-04T23:30:00Z",
        "status": {"type": {"state": "pre", "completed": False}},
        "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"id": "1"}},
            {"homeAway": "away", "team": {"id": "2"}},
        ]}],
    }


class ScheduledFixtureParserTests(unittest.TestCase):
    def test_preserves_provider_identity_and_utc_tipoff(self):
        row = parse_scheduled_nba_fixture(event())
        self.assertEqual(row["provider_fixture_id"], "401999001")
        self.assertEqual(row["home_team_id"], "1")
        self.assertEqual(row["away_team_id"], "2")
        self.assertEqual(row["start_ts_utc"], 1793835000)

    def test_completed_event_not_accepted_as_pregame(self):
        row = event()
        row["status"]["type"] = {"state": "post", "completed": True}
        self.assertIsNone(parse_scheduled_nba_fixture(row))

    def test_missing_or_duplicate_team_identity_rejected(self):
        row = event()
        row["competitions"][0]["competitors"][1]["team"]["id"] = "1"
        self.assertIsNone(parse_scheduled_nba_fixture(row))

    def test_naive_timestamp_rejected(self):
        row = event()
        row["date"] = "2026-11-04T23:30:00"
        self.assertIsNone(parse_scheduled_nba_fixture(row))

    def test_missing_status_rejected(self):
        row = event()
        del row["status"]
        self.assertIsNone(parse_scheduled_nba_fixture(row))


if __name__ == "__main__":
    unittest.main()
