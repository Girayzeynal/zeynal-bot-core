import unittest
from unittest.mock import AsyncMock
from providers.espn_adapter import ESPNAdapter


class ESPNTeamQuoteNormalizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_boundary_quote_does_not_break_exact_team_match(self):
        adapter = ESPNAdapter()
        adapter._load_teams = AsyncMock(return_value=[
            {"team": {"id": "7", "abbreviation": "DEN",
                      "displayName": "Denver Nuggets", "shortDisplayName": "Nuggets"}}
        ])
        self.assertEqual((await adapter.resolve_team('Denver Nuggets"'))["id"], "7")
        self.assertEqual((await adapter.resolve_team("'Denver Nuggets'"))["abbr"], "DEN")

    async def test_unrelated_team_remains_unresolved(self):
        adapter = ESPNAdapter()
        adapter._load_teams = AsyncMock(return_value=[
            {"team": {"id": "7", "abbreviation": "DEN",
                      "displayName": "Denver Nuggets", "shortDisplayName": "Nuggets"}}
        ])
        self.assertIsNone(await adapter.resolve_team("Denver"))
        self.assertIsNone(await adapter.resolve_team('""'))


if __name__ == "__main__":
    unittest.main()
