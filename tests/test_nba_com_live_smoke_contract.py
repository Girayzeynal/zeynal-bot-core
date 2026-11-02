"""Offline contract checks for historical NBA.com smoke validation."""
import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

from providers.nba_com_live_smoke import check


def test_smoke_accepts_distinct_game_ids_on_same_calendar_date():
    now = int(datetime(2026, 11, 2, tzinfo=timezone.utc).timestamp())
    games = [
        {"ts_utc": now - 86400 * (i // 2 + 1), "game_id": f"0022600{i:03d}",
         "source": "nba_com", "pts_for": 100 + i, "pts_against": 90, "pace": None}
        for i in range(6)
    ]
    async def fetch(*args):
        return games
    with patch("providers.nba_com_live_smoke.NBAComAdapter") as factory:
        adapter = factory.return_value
        adapter.fetch_team_recent_games.side_effect = fetch
        adapter.aclose.side_effect = lambda: asyncio.sleep(0)
        result = asyncio.run(check("SA"))
    assert result["status"] == "pass"
    assert result["candidate_game_count"] == 6


def test_smoke_rejects_duplicate_provider_game_id():
    now = int(datetime(2026, 11, 2, tzinfo=timezone.utc).timestamp())
    games = [
        {"ts_utc": now - 86400 * (i + 1), "game_id": "0022600001",
         "source": "nba_com", "pts_for": 100 + i, "pts_against": 90, "pace": None}
        for i in range(6)
    ]
    async def fetch(*args):
        return games
    with patch("providers.nba_com_live_smoke.NBAComAdapter") as factory:
        adapter = factory.return_value
        adapter.fetch_team_recent_games.side_effect = fetch
        adapter.aclose.side_effect = lambda: asyncio.sleep(0)
        result = asyncio.run(check("SA"))
    assert result["status"] == "insufficient_or_invalid"
