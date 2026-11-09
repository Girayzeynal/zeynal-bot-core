import asyncio
from datetime import datetime, timezone
import unittest
from nba_fixture_binding import resolve_nba_fixture


class FixtureBindingTests(unittest.TestCase):
    def test_turkey_date_and_home_away_identity(self):
        class Adapter:
            async def resolve_team(self, name):
                return {"Home": {"id": "1"}, "Away": {"id": "2"}}.get(name)
            async def fetch_scheduled_nba_scoreboard_date(self, day):
                if day != "20261108":
                    return []
                return [{"provider_fixture_id": "401909924",
                         "start_ts_utc": int(datetime(2026, 11, 9, 1, 30, tzinfo=timezone.utc).timestamp()),
                         "home_team_id": "1", "away_team_id": "2"}]
        async def run():
            return await resolve_nba_fixture(Adapter(), "2026-11-09", "Home", "Away",
                now_utc=datetime(2026, 11, 8, 20, tzinfo=timezone.utc))
        self.assertEqual(asyncio.run(run())["provider_fixture_id"], "401909924")

    def test_missing_fixture_fails_closed(self):
        class Adapter:
            async def resolve_team(self, name):
                return {"id": name}
            async def fetch_scheduled_nba_scoreboard_date(self, day):
                return []
        with self.assertRaises(ValueError):
            asyncio.run(resolve_nba_fixture(Adapter(), "2026-11-09", "Home", "Away"))


if __name__ == "__main__":
    unittest.main()
