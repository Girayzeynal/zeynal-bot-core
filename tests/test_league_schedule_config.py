"""Validate scheduled API-Sports league identifiers in deployment configuration."""
import json
import unittest
from pathlib import Path


class LeagueScheduleConfigTests(unittest.TestCase):
    def test_enabled_schedules_have_positive_integer_api_sports_ids(self):
        path = Path(__file__).resolve().parents[1] / "leagues.json"
        leagues = json.loads(path.read_text(encoding="utf-8"))
        self.assertIsInstance(leagues, list)
        self.assertTrue(leagues, "league configuration must not be empty")
        for league in leagues:
            with self.subTest(league=league.get("name")):
                if league.get("enabled_schedule") is True:
                    league_id = league.get("api_sports_league_id")
                    self.assertIs(type(league_id), int)
                    self.assertGreater(league_id, 0)

    def test_bcl_remains_disabled_until_verified_id_is_configured(self):
        path = Path(__file__).resolve().parents[1] / "leagues.json"
        leagues = json.loads(path.read_text(encoding="utf-8"))
        bcl = [item for item in leagues if item.get("name") == "BCL"]
        self.assertEqual(len(bcl), 1)
        if bcl[0].get("api_sports_league_id") == 0:
            self.assertIs(bcl[0].get("enabled_schedule"), False)


if __name__ == "__main__":
    unittest.main()
