import unittest
from nba_command import parse_espn_scoreboard, select_local_games


class FixtureIdentityTests(unittest.TestCase):
    def test_espn_id_survives_timezone_filter(self):
        payload = {"events": [{
            "id": "401999999",
            "date": "2026-11-09T23:30:00Z",
            "competitions": [{"competitors": [
                {"homeAway": "home", "team": {"displayName": "Home"}},
                {"homeAway": "away", "team": {"displayName": "Away"}},
            ]}],
            "status": {"type": {"name": "STATUS_SCHEDULED"}},
        }]}
        games = parse_espn_scoreboard(payload, "2026-11-10")
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]["id"], "401999999")
        self.assertEqual(games[0]["start"].hour, 2)

    def test_missing_id_is_rejected(self):
        self.assertEqual(select_local_games([{
            "date": "2026-11-09T23:30:00Z",
            "teams": {"home": {"name": "Home"}, "away": {"name": "Away"}},
            "status": {"short": "Scheduled"},
        }], "2026-11-10"), [])


if __name__ == "__main__":
    unittest.main()
