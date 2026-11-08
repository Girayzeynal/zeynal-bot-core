import unittest
from unittest.mock import patch

from faz17_engine.faz17_engine import Faz17Engine, MarketRequest


class FakeResponse:
    status = 200

    def __init__(self, event):
        self.event = event

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        return [self.event]


class FakeSession:
    def __init__(self, event):
        self.event = event

    def get(self, *args, **kwargs):
        return FakeResponse(self.event)


class MarketFreshnessBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def _fetch(self, quote_age):
        now = 1794183000
        from datetime import datetime, timezone
        stamp = datetime.fromtimestamp(now - quote_age, timezone.utc).isoformat()
        event = {
            "home_team": "Houston Rockets",
            "away_team": "Denver Nuggets",
            "commence_time": "2026-11-10T01:30:00Z",
            "bookmakers": [{
                "key": "testbook", "last_update": stamp,
                "markets": [{"key": "totals", "outcomes": [
                    {"name": "Over", "point": 222.5, "price": 1.91},
                    {"name": "Under", "point": 222.5, "price": 1.91},
                ]}],
            }],
        }
        engine = Faz17Engine(api_key="test-key")
        async def session():
            return FakeSession(event)
        engine._get_session = session
        req = MarketRequest(league="NBA", home="Houston Rockets", away="Denver Nuggets",
                            date_str="2026-11-10", fixture_start_utc=1794274200)
        with patch("faz17_engine.faz17_engine.time.time", return_value=now):
            return await engine.fetch_market(req)

    async def test_fresh_quote_is_accepted(self):
        result = await self._fetch(60)
        self.assertEqual(result["status"], "MARKET_OK")
        self.assertEqual(result["total"], 222.5)
        self.assertEqual(len(result["quotes"]), 1)

    async def test_stale_quote_is_not_displayed(self):
        result = await self._fetch(901)
        self.assertIsNone(result["total"])
        self.assertEqual(result["status"], "MARKET_OPTIONAL")

    async def test_future_quote_is_not_displayed(self):
        result = await self._fetch(-30)
        self.assertIsNone(result["total"])
        self.assertEqual(result["status"], "MARKET_OPTIONAL")


if __name__ == "__main__":
    unittest.main()
