import unittest
from datetime import datetime, timezone

from providers.espn_completed_event import parse_completed_nba_event


def event():
    return {
        "id": "401000123",
        "date": "2026-10-25T23:00:00Z",
        "competitions": [{
            "status": {"type": {"state": "completed", "completed": True}},
            "competitors": [
                {"homeAway": "home", "team": {"id": "1"}, "score": "115"},
                {"homeAway": "away", "team": {"id": "2"}, "score": "109"},
            ],
        }],
    }


NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


class ESPNCompletedEventTests(unittest.TestCase):
    def test_valid_completed_event(self):
        row = parse_completed_nba_event(event(), NOW)
        self.assertEqual(row["provider_fixture_id"], "401000123")
        self.assertEqual(row["actual_home"], 115)
        self.assertEqual(row["actual_away"], 109)
        self.assertEqual(row["start_ts_utc"], 1792969200)

    def test_reject_incomplete_game(self):
        e = event()
        e["competitions"][0]["status"]["type"]["completed"] = False
        self.assertIsNone(parse_completed_nba_event(e, NOW))

    def test_reject_ambiguous_teams(self):
        e = event()
        e["competitions"][0]["competitors"][1]["homeAway"] = "home"
        self.assertIsNone(parse_completed_nba_event(e, NOW))

    def test_reject_future_event(self):
        e = event()
        e["date"] = "2026-11-02T23:00:00Z"
        self.assertIsNone(parse_completed_nba_event(e, NOW))

    def test_reject_fractional_score(self):
        e = event()
        e["competitions"][0]["competitors"][0]["score"] = "115.5"
        self.assertIsNone(parse_completed_nba_event(e, NOW))


if __name__ == "__main__":
    unittest.main()
