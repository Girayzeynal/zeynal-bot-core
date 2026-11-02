import unittest
from unittest.mock import AsyncMock

from providers.espn_adapter import ESPNAdapter


def event(event_id, score="115"):
    return {
        "id": event_id, "date": "2025-10-25T23:00:00Z",
        "competitions": [{
            "status": {"type": {"state": "completed", "completed": True}},
            "competitors": [
                {"homeAway": "home", "team": {"id": "1"}, "score": score},
                {"homeAway": "away", "team": {"id": "2"}, "score": "108"},
            ],
        }],
    }


class ESPNScoreboardQualityReportTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_fetch_audits_and_excludes_conflicts(self):
        adapter = ESPNAdapter()
        adapter._get_json = AsyncMock(return_value={"events": [
            event("a"), event("a", "116"), event("b"),
        ]})
        result = await adapter.fetch_nba_scoreboard_quality_report("20251025", observed_at_utc=1761500000)
        adapter._get_json.assert_awaited_once()
        self.assertEqual(result["observed_at_utc"], 1761500000)
        self.assertEqual(result["quality"]["conflicting_fixture_ids_detail"], ["a"])
        self.assertEqual(result["quality"]["accepted_unique"], 1)
        self.assertEqual(
            [e["provider_fixture_id"] for e in result["completed_events"]], ["b"]
        )

    async def test_event_after_observation_is_excluded_consistently(self):
        adapter = ESPNAdapter()
        adapter._get_json = AsyncMock(return_value={"events": [event("a")]})
        result = await adapter.fetch_nba_scoreboard_quality_report(
            "20251025", observed_at_utc=1761300000
        )
        self.assertEqual(result["quality"]["accepted_unique"], 0)
        self.assertEqual(result["quality"]["invalid_or_incomplete"], 1)
        self.assertEqual(result["completed_events"], [])

    async def test_fetch_failure_not_reported_as_empty_game_day(self):
        adapter = ESPNAdapter()
        adapter._get_json = AsyncMock(return_value=None)
        with self.assertRaises(RuntimeError):
            await adapter.fetch_nba_scoreboard_quality_report("20251025")

    async def test_invalid_date_does_not_fetch(self):
        adapter = ESPNAdapter()
        adapter._get_json = AsyncMock()
        with self.assertRaises(ValueError):
            await adapter.fetch_nba_scoreboard_quality_report("20250230")
        adapter._get_json.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
