import unittest
from providers.espn_adapter import ESPNAdapter


class EspnTeamIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_alias_for_different_team_ids_is_ambiguous(self):
        adapter = ESPNAdapter()
        adapter._teams_cache = [
            {"team": {"id": "1", "abbreviation": "ABC", "displayName": "One"}},
            {"team": {"id": "2", "abbreviation": "ABC", "displayName": "Two"}},
        ]
        import time
        adapter._teams_cache_ts = time.time()
        self.assertIsNone(await adapter.resolve_team("ABC"))

    async def test_repeated_same_team_id_is_not_ambiguous(self):
        adapter = ESPNAdapter()
        adapter._teams_cache = [
            {"team": {"id": "1", "abbreviation": "ABC", "displayName": "One"}},
            {"team": {"id": "1", "abbreviation": "ABC", "displayName": "One"}},
        ]
        import time
        adapter._teams_cache_ts = time.time()
        self.assertEqual((await adapter.resolve_team("ABC"))["id"], "1")

    async def test_unmatched_team_is_not_guessed(self):
        adapter = ESPNAdapter()
        adapter._teams_cache = [
            {"team": {"id": "1", "abbreviation": "ABC", "displayName": "One"}},
        ]
        import time
        adapter._teams_cache_ts = time.time()
        self.assertIsNone(await adapter.resolve_team("Other"))


if __name__ == "__main__":
    unittest.main()
