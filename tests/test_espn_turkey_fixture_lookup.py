import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from providers.espn_adapter import ESPNAdapter
from providers.espn_turkey_fixture_lookup import resolve_nba_fixture_for_turkey_date, resolve_named_nba_fixture_for_turkey_date


def fixture(id_, timestamp, home="1", away="2"):
    return dict(provider="ESPN", provider_fixture_id=id_, start_ts_utc=timestamp,
                home_team_id=home, away_team_id=away)


class TurkeyFixtureLookupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.adapter = ESPNAdapter()
        self.adapter.fetch_scheduled_nba_scoreboard_date = AsyncMock(return_value=[])

    async def test_previous_utc_date_is_included(self):
        tipoff = int(datetime(2026, 11, 3, 22, 30, tzinfo=timezone.utc).timestamp())
        self.adapter.fetch_scheduled_nba_scoreboard_date.side_effect = [
            [fixture("espn-1", tipoff)], [],
        ]
        row = await resolve_nba_fixture_for_turkey_date(
            self.adapter, "2026-11-04", home_team_id="1", away_team_id="2")
        self.assertEqual(row["provider_fixture_id"], "espn-1")
        self.assertEqual(self.adapter.fetch_scheduled_nba_scoreboard_date.await_args_list[0].args[0], "20261103")
        self.assertEqual(self.adapter.fetch_scheduled_nba_scoreboard_date.await_args_list[1].args[0], "20261104")

    async def test_rejects_other_turkey_calendar_day(self):
        tipoff = int(datetime(2026, 11, 4, 22, 30, tzinfo=timezone.utc).timestamp())
        self.adapter.fetch_scheduled_nba_scoreboard_date.return_value = [fixture("espn-1", tipoff)]
        with self.assertRaises(ValueError):
            await resolve_nba_fixture_for_turkey_date(
                self.adapter, "2026-11-04", home_team_id="1", away_team_id="2")

    async def test_duplicate_same_id_deduplicates(self):
        tipoff = int(datetime(2026, 11, 4, 1, 30, tzinfo=timezone.utc).timestamp())
        self.adapter.fetch_scheduled_nba_scoreboard_date.return_value = [fixture("espn-1", tipoff)]
        row = await resolve_nba_fixture_for_turkey_date(
            self.adapter, "2026-11-04", home_team_id="1", away_team_id="2")
        self.assertEqual(row["provider_fixture_id"], "espn-1")

    async def test_two_distinct_fixtures_fail_closed(self):
        tipoff = int(datetime(2026, 11, 4, 1, 30, tzinfo=timezone.utc).timestamp())
        self.adapter.fetch_scheduled_nba_scoreboard_date.return_value = [
            fixture("espn-1", tipoff), fixture("espn-2", tipoff)]
        with self.assertRaises(ValueError):
            await resolve_nba_fixture_for_turkey_date(
                self.adapter, "2026-11-04", home_team_id="1", away_team_id="2")

    async def test_named_team_resolution_uses_espn_ids(self):
        tipoff = int(datetime(2026, 11, 4, 1, 30, tzinfo=timezone.utc).timestamp())
        self.adapter.resolve_team = AsyncMock(side_effect=[
            {"id": "1", "name": "Home"}, {"id": "2", "name": "Away"},
        ])
        self.adapter.fetch_scheduled_nba_scoreboard_date.return_value = [
            fixture("espn-1", tipoff)]
        row = await resolve_named_nba_fixture_for_turkey_date(
            self.adapter, "2026-11-04", home="Home", away="Away")
        self.assertEqual(row["provider_fixture_id"], "espn-1")
        self.assertEqual(self.adapter.resolve_team.await_count, 2)

    async def test_unresolved_team_rejects_before_scoreboard_fetch(self):
        self.adapter.resolve_team = AsyncMock(side_effect=[{"id": "1"}, None])
        with self.assertRaises(ValueError):
            await resolve_named_nba_fixture_for_turkey_date(
                self.adapter, "2026-11-04", home="Home", away="Unknown")
        self.adapter.fetch_scheduled_nba_scoreboard_date.assert_not_awaited()

    async def test_swapped_team_ids_do_not_match(self):
        tipoff = int(datetime(2026, 11, 4, 1, 30, tzinfo=timezone.utc).timestamp())
        self.adapter.resolve_team = AsyncMock(side_effect=[{"id": "2"}, {"id": "1"}])
        self.adapter.fetch_scheduled_nba_scoreboard_date.return_value = [
            fixture("espn-1", tipoff)]
        with self.assertRaises(ValueError):
            await resolve_named_nba_fixture_for_turkey_date(
                self.adapter, "2026-11-04", home="Away", away="Home")

    async def test_provider_failure_propagates(self):
        self.adapter.fetch_scheduled_nba_scoreboard_date.side_effect = RuntimeError("offline")
        with self.assertRaises(RuntimeError):
            await resolve_nba_fixture_for_turkey_date(
                self.adapter, "2026-11-04", home_team_id="1", away_team_id="2")


if __name__ == "__main__":
    unittest.main()
