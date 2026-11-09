"""Regression checks for leagues configured for automatic API-Sports polling."""
import json
import unittest
from pathlib import Path


CATALOG = Path(__file__).resolve().parents[1] / "leagues.json"


class LeagueCatalogTests(unittest.TestCase):
    def test_bcl_is_not_in_automatic_catalog(self):
        leagues = json.loads(CATALOG.read_text(encoding="utf-8"))
        self.assertNotIn("BCL", [league.get("name") for league in leagues])

    def test_enabled_leagues_have_valid_numeric_provider_ids(self):
        leagues = json.loads(CATALOG.read_text(encoding="utf-8"))
        for league in leagues:
            if league.get("enabled_schedule") is True:
                with self.subTest(league=league.get("name")):
                    provider_id = league.get("api_sports_league_id")
                    self.assertIs(type(provider_id), int)
                    self.assertGreater(provider_id, 0)


if __name__ == "__main__":
    unittest.main()
