import unittest
from unittest.mock import AsyncMock

from providers.espn_daily_quality import collect_nba_daily_quality


class ESPNDailyQualityTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_empty_and_failure_remain_distinct(self):
        async def fetch(date):
            if date == "20251026":
                raise RuntimeError("ESPN unavailable")
            count = 2 if date == "20251025" else 0
            return {"quality": {"total_raw": count, "accepted_unique": count}}
        adapter = type("Adapter", (), {})()
        adapter.fetch_nba_scoreboard_quality_report = AsyncMock(side_effect=fetch)
        report = await collect_nba_daily_quality(adapter, [
            "20251025", "20251026", "20251027", "20251025",
        ])
        self.assertEqual(report["dates_requested"], 3)
        self.assertEqual(report["dates_successful"], 2)
        self.assertEqual(report["dates_failed"], 1)
        self.assertEqual(report["raw_events_successful_dates"], 2)
        self.assertEqual(report["accepted_unique_successful_dates"], 2)
        self.assertEqual([r["status"] for r in report["daily"]],
                         ["ok", "fetch_or_validation_error", "ok"])
        self.assertEqual(adapter.fetch_nba_scoreboard_quality_report.await_count, 3)

    async def test_invalid_input_is_rejected(self):
        adapter = type("Adapter", (), {})()
        adapter.fetch_nba_scoreboard_quality_report = AsyncMock()
        with self.assertRaises(ValueError):
            await collect_nba_daily_quality(adapter, [20251025])
        adapter.fetch_nba_scoreboard_quality_report.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
