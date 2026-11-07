import unittest
from unittest.mock import AsyncMock

from providers.espn_adapter import ESPNAdapter


def fixture(event_id="401999001", home="1", away="2"):
    return {
        "id": event_id, "date": "2026-11-04T23:30:00Z",
        "status": {"type": {"state": "pre", "completed": False}},
        "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"id": home}},
            {"homeAway": "away", "team": {"id": away}},
        ]}],
    }


class ScheduledScoreboardTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_and_deduplicates_identical_fixture(self):
        adapter = ESPNAdapter()
        adapter._get_json = AsyncMock(return_value={"events": [
            fixture(), fixture(), fixture("401999002", "3", "4"),
        ]})
        rows = await adapter.fetch_scheduled_nba_scoreboard_date("20261104")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["provider_fixture_id"], "401999001")

    async def test_conflicting_duplicate_identity_excluded(self):
        adapter = ESPNAdapter()
        adapter._get_json = AsyncMock(return_value={"events": [
            fixture(), fixture("401999001", "3", "4"),
        ]})
        rows = await adapter.fetch_scheduled_nba_scoreboard_date("20261104")
        self.assertEqual(rows, [])

    async def test_failed_provider_request_is_not_empty_schedule(self):
        adapter = ESPNAdapter()
        adapter._get_json = AsyncMock(return_value=None)
        with self.assertRaises(RuntimeError):
            await adapter.fetch_scheduled_nba_scoreboard_date("20261104")

    async def test_rejects_invalid_calendar_date(self):
        adapter = ESPNAdapter()
        adapter._get_json = AsyncMock()
        with self.assertRaises(ValueError):
            await adapter.fetch_scheduled_nba_scoreboard_date("20260230")
        adapter._get_json.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
