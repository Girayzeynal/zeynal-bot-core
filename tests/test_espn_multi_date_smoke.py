import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from providers.espn_multi_date_smoke import check_dates, main


class ESPNMultiDateSmokeTests(unittest.TestCase):
    def test_collects_distinct_days(self):
        async def fake(date):
            return {"quality": {"total_raw": 2, "accepted_unique": 1},
                    "completed_events_count": 1,
                    "completed_fixture_ids": [date + "-fixture"],
                    "date_yyyymmdd": date}
        with patch("providers.espn_multi_date_smoke.check_scoreboard", side_effect=fake):
            result = asyncio.run(check_dates(["20251025", "20251026"]))
        self.assertEqual(result["dates_checked"], 2)
        self.assertEqual(result["total_raw"], 4)
        self.assertEqual(result["accepted_unique"], 2)

    def test_fails_closed_if_any_date_fails(self):
        async def fake(date):
            if date == "20251026":
                raise RuntimeError("identity anomaly")
            return {"quality": {"total_raw": 1, "accepted_unique": 1},
                    "completed_events_count": 1,
                    "completed_fixture_ids": [date + "-fixture"]}
        with patch("providers.espn_multi_date_smoke.check_scoreboard", side_effect=fake):
            with self.assertRaisesRegex(RuntimeError, "identity anomaly"):
                asyncio.run(check_dates(["20251025", "20251026"]))

    def test_duplicate_fixture_across_dates_rejected(self):
        async def fake(date):
            return {"quality": {"total_raw": 1, "accepted_unique": 1},
                    "completed_events_count": 1,
                    "completed_fixture_ids": ["same-fixture"]}
        with patch("providers.espn_multi_date_smoke.check_scoreboard", side_effect=fake):
            with self.assertRaisesRegex(RuntimeError, "across dates"):
                asyncio.run(check_dates(["20251025", "20251026"]))

    def test_duplicate_date_rejected(self):
        self.assertEqual(main(["20251025", "20251025"]), 2)


if __name__ == "__main__":
    unittest.main()
