import unittest
from unittest.mock import AsyncMock

from providers.espn_adapter import ESPNAdapter


def sample_event(event_id, complete=True):
    return {
        "id": event_id, "date": "2025-10-25T23:00:00Z",
        "competitions": [{
            "status": {"type": {
                "state": "completed" if complete else "in",
                "completed": complete,
            }},
            "competitors": [
                {"homeAway": "home", "team": {"id": "1"}, "score": "115"},
                {"homeAway": "away", "team": {"id": "2"}, "score": "108"},
            ],
        }],
    }


class ESPNScoreboardDateTests(unittest.IsolatedAsyncioTestCase):
    async def test_completed_only_deduplicated(self):
        adapter = ESPNAdapter()
        adapter._get_json = AsyncMock(return_value={"events": [
            sample_event("123"), sample_event("123"),
            sample_event("124", complete=False),
        ]})
        result = await adapter.fetch_completed_nba_scoreboard_date("20251025")
        self.assertEqual([r["provider_fixture_id"] for r in result], ["123"])
        adapter._get_json.assert_awaited_once()

    async def test_conflicting_duplicate_fixture_is_excluded(self):
        adapter = ESPNAdapter()
        changed = sample_event("123")
        changed["competitions"][0]["competitors"][0]["score"] = "116"
        adapter._get_json = AsyncMock(return_value={"events": [
            sample_event("123"), changed, sample_event("125")
        ]})
        result = await adapter.fetch_completed_nba_scoreboard_date("20251025")
        self.assertEqual([r["provider_fixture_id"] for r in result], ["125"])

    async def test_invalid_date_does_not_fetch(self):
        adapter = ESPNAdapter()
        adapter._get_json = AsyncMock()
        for value in ("20250230", "2025-10-25", "2025102x"):
            with self.assertRaises(ValueError):
                await adapter.fetch_completed_nba_scoreboard_date(value)
        adapter._get_json.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
