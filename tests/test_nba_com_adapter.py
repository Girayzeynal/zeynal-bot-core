"""Offline contract tests for NBA.com baseline candidate."""
import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

from providers.nba_com_adapter import NBAComAdapter


class FakeResponse:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self, content_type=None):
        headers = ["TEAM_ID", "GAME_ID", "GAME_DATE", "MATCHUP", "PTS", "PLUS_MINUS", "WL"]
        return {"resultSets": [{"headers": headers, "rowSet": [
            [1610612759, "0022600001", "2026-10-20", "SAS vs. UTA", 110, 10, "W"],
            [1610612759, "0022600002", "2026-10-21", "SAS @ UTA", 99, -8, "L"],
            [1610612759, "0022600003", "2026-10-22", "SAS vs. UTA", 90, -5, "W"],
            [1610612759, "0022600004", "2026-11-04", "SAS vs. UTA", 110, 10, "W"],
            [1610612759, "0022600005", "2026-10-23", "SAS vs. UTA", 101, 0, "W"],
            [1610612762, "0022600006", "2026-10-24", "UTA vs. SAS", 100, 5, "W"],
        ]}]}


class FakeSession:
    closed = False

    def get(self, url, params=None):
        return FakeResponse()


def test_nba_com_filters_invalid_and_future_rows():
    adapter = NBAComAdapter(session=FakeSession())
    with patch("providers.nba_com_adapter.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime(2026, 11, 2, tzinfo=timezone.utc)
        mock_datetime.strptime.side_effect = datetime.strptime
        games = asyncio.run(adapter.fetch_team_recent_games("NBA", "SA", 10))
    assert len(games) == 2
    assert games[0]["pts_for"] == 110
    assert games[0]["pts_against"] == 100
    assert games[0]["home"] is True
    assert games[1]["pts_for"] == 99
    assert games[1]["pts_against"] == 107
    assert games[1]["home"] is False


def test_nba_com_rejects_unsupported_leagues_and_unknown_teams():
    adapter = NBAComAdapter(session=FakeSession())
    assert asyncio.run(adapter.fetch_team_recent_games("EuroLeague", "SA", 10)) is None
    assert asyncio.run(adapter.fetch_team_recent_games("NBA", "UNKNOWN", 10)) is None
    assert asyncio.run(adapter.fetch_team_recent_games("NBA", "SA", 0)) is None
