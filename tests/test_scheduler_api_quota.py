"""Regression checks for API-Sports quota handling (no network calls)."""
import asyncio
import unittest
from datetime import datetime, timezone

import dynamic_scheduler as scheduler


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def raise_for_status(self):
        return None

    async def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return FakeResponse(self.payload)


class SchedulerQuotaTests(unittest.TestCase):
    def setUp(self):
        scheduler._fixture_cache.clear()
        scheduler._quota_retry_at = None

    def tearDown(self):
        scheduler._fixture_cache.clear()
        scheduler._quota_retry_at = None

    def test_quota_error_with_http_200_is_detected(self):
        self.assertTrue(scheduler.api_sports_quota_exhausted({
            "errors": {"requests": "You have reached the request limit for the day."},
            "results": 0,
            "response": [],
        }))
        self.assertFalse(scheduler.api_sports_quota_exhausted({
            "errors": [], "response": [],
        }))

    def test_quota_response_stops_repeated_requests(self):
        session = FakeSession({
            "errors": {"requests": "You have reached the request limit for the day."},
            "response": [],
        })
        self.assertEqual(asyncio.run(scheduler.fetch_games(12, "2026-11-07", session)), [])
        self.assertIsNotNone(scheduler._quota_retry_at)
        self.assertGreater(scheduler._quota_retry_at, datetime.now(timezone.utc))
        self.assertEqual(asyncio.run(scheduler.fetch_games(120, "2026-11-07", session)), [])
        self.assertEqual(session.calls, 1)

    def test_successful_empty_response_is_cached(self):
        session = FakeSession({"errors": [], "response": []})
        self.assertEqual(asyncio.run(scheduler.fetch_games(12, "2026-11-07", session)), [])
        self.assertEqual(asyncio.run(scheduler.fetch_games(12, "2026-11-07", session)), [])
        self.assertEqual(session.calls, 1)

    def test_other_provider_error_is_not_cached(self):
        session = FakeSession({"errors": {"token": "Invalid key"}, "response": []})
        asyncio.run(scheduler.fetch_games(12, "2026-11-07", session))
        asyncio.run(scheduler.fetch_games(12, "2026-11-07", session))
        self.assertEqual(session.calls, 2)


if __name__ == "__main__":
    unittest.main()
