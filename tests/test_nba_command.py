import os
import unittest
from unittest.mock import patch
from datetime import datetime, timezone

from nba_command import load_nba_games, parse_nba_date, select_local_games, utc_dates_for_turkey_day, validate_provider_payload


class NbaCommandTests(unittest.TestCase):
    def test_default_date_uses_turkey_time(self):
        now = datetime(2026, 11, 3, 22, 30, tzinfo=timezone.utc)
        self.assertEqual(parse_nba_date([], now), "2026-11-04")

    def test_invalid_date_rejected(self):
        with self.assertRaises(ValueError):
            parse_nba_date(["2026-02-30"], datetime.now(timezone.utc))

    def test_local_day_boundary_and_deduplication(self):
        game = {
            "id": 101, "date": "2026-11-03T22:30:00+00:00",
            "teams": {"home": {"name": "Home"}, "away": {"name": "Away"}},
            "status": {"short": "NS"},
        }
        self.assertEqual(len(select_local_games([game, game], "2026-11-04")), 1)
        self.assertEqual(len(select_local_games([game], "2026-11-03")), 0)

    def test_malformed_game_skipped(self):
        self.assertEqual(select_local_games([{"id": 1}], "2026-11-04"), [])

    def test_invalid_game_identifiers_skipped(self):
        template = {
            "date": "2026-11-03T22:30:00Z",
            "teams": {"home": {"name": "Home"}, "away": {"name": "Away"}},
            "status": {"short": "NS"},
        }
        rows = [{**template, "id": value} for value in (None, "", True, [], {})]
        self.assertEqual(select_local_games(rows, "2026-11-04"), [])

    def test_turkey_day_uses_two_utc_dates(self):
        self.assertEqual(utc_dates_for_turkey_day("2026-11-04"), ["2026-11-03", "2026-11-04"])

    def test_utc_day_boundary_at_both_ends(self):
        template = {
            "teams": {"home": {"name": "Home"}, "away": {"name": "Away"}},
            "status": {"short": "NS"},
        }
        rows = [
            {**template, "id": 1, "date": "2026-11-03T20:59:59Z"},
            {**template, "id": 2, "date": "2026-11-03T21:00:00Z"},
            {**template, "id": 3, "date": "2026-11-04T20:59:59Z"},
            {**template, "id": 4, "date": "2026-11-04T21:00:00Z"},
        ]
        self.assertEqual(len(select_local_games(rows, "2026-11-04")), 2)

    def test_provider_payload_rejects_errors(self):
        for errors in ({"token": "invalid"}, ["quota exceeded"], "error"):
            with self.subTest(errors=errors), self.assertRaises(ValueError):
                validate_provider_payload({"errors": errors, "response": []})

    def test_provider_payload_rejects_invalid_shapes(self):
        for payload in (None, [], {}, {"response": None}, {"response": [None]}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                validate_provider_payload(payload)

    def test_provider_payload_accepts_empty_valid_response(self):
        self.assertEqual(validate_provider_payload({"errors": [], "response": []}), [])

    def test_invalid_rows_skipped(self):
        self.assertEqual(select_local_games([None, [], "invalid"], "2026-11-04"), [])


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def raise_for_status(self):
        return None

    async def json(self):
        return self.payload


class FakeSession:
    requests = []
    payloads = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def get(self, url, *, headers, params):
        self.requests.append((url, headers, params))
        return FakeResponse(self.payloads[len(self.requests) - 1])


class NbaHttpContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_two_dates_and_headers(self):
        FakeSession.requests = []
        FakeSession.payloads = [
            {"errors": [], "response": []},
            {"errors": [], "response": []},
        ]
        with patch.dict(os.environ, {"API_SPORTS_KEY": "test-key", "API_SPORTS_BASE": "https://example.test"}), patch("nba_command.aiohttp.ClientSession", FakeSession):
            games = await load_nba_games("2026-11-04")
        self.assertEqual(games, [])
        self.assertEqual(len(FakeSession.requests), 2)
        self.assertEqual([r[2]["date"] for r in FakeSession.requests], ["2026-11-03", "2026-11-04"])
        self.assertTrue(all(r[2]["league"] == 12 and r[2]["timezone"] == "UTC" for r in FakeSession.requests))
        self.assertTrue(all(r[1] == {"x-apisports-key": "test-key"} for r in FakeSession.requests))

    async def test_provider_error_fails_closed(self):
        FakeSession.requests = []
        FakeSession.payloads = [{"errors": {"token": "invalid"}, "response": []}]
        with patch.dict(os.environ, {"API_SPORTS_KEY": "test-key"}), patch("nba_command.aiohttp.ClientSession", FakeSession):
            with self.assertRaises(ValueError):
                await load_nba_games("2026-11-04")
        self.assertEqual(len(FakeSession.requests), 1)

    async def test_missing_api_key_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                await load_nba_games("2026-11-04")


if __name__ == "__main__":
    unittest.main()
