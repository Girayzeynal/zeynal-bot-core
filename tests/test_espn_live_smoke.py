import io
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

from providers.espn_live_smoke import main, check_scoreboard


class ESPNSmokeCLITests(unittest.TestCase):
    def test_mismatched_accepted_count_is_rejected(self):
        from unittest.mock import AsyncMock
        import asyncio
        adapter = type("Adapter", (), {})()
        adapter.fetch_nba_scoreboard_quality_report = AsyncMock(return_value={
            "observed_at_utc": 1761500000,
            "quality": {
                "total_raw": 1, "accepted_unique": 1,
                "invalid_or_incomplete": 0, "duplicate_identical": 0,
                "conflicting_records": 0,
            },
            "completed_events": [],
        })
        adapter.aclose = AsyncMock()
        with patch("providers.espn_live_smoke.ESPNAdapter", return_value=adapter):
            with self.assertRaisesRegex(RuntimeError, "accepted count"):
                asyncio.run(check_scoreboard("20251025"))
        adapter.aclose.assert_awaited_once()

    def test_identity_anomaly_fails_closed(self):
        from unittest.mock import AsyncMock
        import asyncio
        adapter = type("Adapter", (), {})()
        adapter.fetch_nba_scoreboard_quality_report = AsyncMock(return_value={
            "observed_at_utc": 1761500000,
            "quality": {
                "total_raw": 1, "accepted_unique": 1,
                "invalid_or_incomplete": 0, "duplicate_identical": 0,
                "conflicting_records": 0,
                "identity_audit": {
                    "eastern_date_mismatch_fixture_ids": ["fixture-a"],
                    "duplicate_fixture_ids": [],
                    "teams_in_multiple_accepted_games": [],
                },
            },
            "completed_events": [{"provider_fixture_id": "fixture-a"}],
        })
        adapter.aclose = AsyncMock()
        with patch("providers.espn_live_smoke.ESPNAdapter", return_value=adapter):
            with self.assertRaisesRegex(RuntimeError, "identity anomaly"):
                asyncio.run(check_scoreboard("20251025"))
        adapter.aclose.assert_awaited_once()

    def test_bad_date_rejected(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(["20260230"]), 2)
            self.assertEqual(main([]), 2)

    def test_unavailable_response_fails_closed(self):
        async def unavailable(date):
            raise RuntimeError("unavailable")
        output = io.StringIO()
        with patch("providers.espn_live_smoke.check_scoreboard", unavailable):
            with redirect_stdout(output):
                self.assertEqual(main(["20261031"]), 1)
        self.assertIn('"status": "error"', output.getvalue())

    def test_verified_response_succeeds(self):
        async def available(date):
            return {"status": "verified_response", "date_yyyymmdd": date,
                    "completed_events_count": 0}
        output = io.StringIO()
        with patch("providers.espn_live_smoke.check_scoreboard", available):
            with redirect_stdout(output):
                self.assertEqual(main(["20261031"]), 0)
        self.assertIn('"verified_response"', output.getvalue())


if __name__ == "__main__":
    unittest.main()
