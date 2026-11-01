import unittest
from unittest.mock import AsyncMock

from providers.espn_adapter import ESPNAdapter


def event(event_id, date, home_id="1", away_id="2", complete=True):
    return {
        "id": event_id,
        "date": date,
        "competitions": [{
            "status": {"type": {"state": "completed" if complete else "in",
                                 "completed": complete}},
            "competitors": [
                {"homeAway": "home", "team": {"id": home_id}, "score": "110"},
                {"homeAway": "away", "team": {"id": away_id}, "score": "100"},
            ],
        }],
    }


class ESPNCompletedFetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_filters_unrelated_and_incomplete_games(self):
        adapter = ESPNAdapter()
        adapter.resolve_team = AsyncMock(return_value={"id": "1", "abbr": "BOS"})
        adapter._get_json = AsyncMock(return_value={"events": [
            event("a", "2025-10-20T20:00:00Z"),
            event("b", "2025-10-21T20:00:00Z", home_id="3", away_id="4"),
            event("c", "2025-10-22T20:00:00Z", complete=False),
        ]})
        result = await adapter.fetch_completed_nba_events("BOS")
        self.assertEqual([r["provider_fixture_id"] for r in result], ["a"])

    async def test_rejects_invalid_limit(self):
        with self.assertRaises(ValueError):
            await ESPNAdapter().fetch_completed_nba_events("BOS", 0)


if __name__ == "__main__":
    unittest.main()
