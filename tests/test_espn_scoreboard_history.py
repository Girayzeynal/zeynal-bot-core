"""Offline regression tests for fail-closed ESPN scoreboard history."""
import asyncio
from datetime import datetime, timezone

from providers.espn_scoreboard_history import ESPNScoreboardHistory


def event(game_id, date, home_score="110", away_score="100"):
    return {
        "id": game_id, "date": date + "T20:00:00Z",
        "competitions": [{
            "status": {"type": {"state": "post", "completed": True}},
            "competitors": [
                {"homeAway": "home", "team": {"id": "24"}, "score": home_score},
                {"homeAway": "away", "team": {"id": "26"}, "score": away_score},
            ],
        }],
    }


def check(adapter, minimum=1):
    return asyncio.run(adapter.fetch_verified_games(
        "24", as_of_utc=datetime(2026, 11, 2, tzinfo=timezone.utc),
        days=2, minimum=minimum))


def test_deduplicates_repeated_scoreboard_games():
    adapter = ESPNScoreboardHistory()
    async def fetch(day):
        return [event("100", "2026-10-20")]
    adapter._fetch_day = fetch
    result = check(adapter)
    assert result is not None and len(result) == 1


def test_rejects_conflicting_game_ids():
    adapter = ESPNScoreboardHistory()
    async def fetch(day):
        return [event("100", "2026-10-20"), event("100", "2026-10-20", home_score="120")]
    adapter._fetch_day = fetch
    assert check(adapter) is None


def test_fails_closed_on_unavailable_date():
    adapter = ESPNScoreboardHistory()
    async def fetch(day):
        return None
    adapter._fetch_day = fetch
    assert check(adapter) is None


def test_excludes_future_events_and_invalid_scores():
    adapter = ESPNScoreboardHistory()
    async def fetch(day):
        return [event("100", "2026-11-03"), event("101", "2026-10-20", home_score="bad")]
    adapter._fetch_day = fetch
    assert check(adapter) is None


def test_minimum_history_is_enforced():
    adapter = ESPNScoreboardHistory()
    async def fetch(day):
        return [event("100", "2026-10-20")]
    adapter._fetch_day = fetch
    assert check(adapter, minimum=6) is None
