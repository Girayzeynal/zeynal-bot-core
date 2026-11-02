"""Pure, fail-closed validation of historical ESPN scoreboard games.

No fabricated possessions/pace. No writes to the production baseline store.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def validate_history_for_fixture(
    games: Any, *, team_id: str, fixture_start_utc: datetime,
    minimum: int = 6, require_pace: bool = True,
) -> dict:
    if (not isinstance(team_id, str) or not team_id.isascii() or not team_id.isdigit()
            or not isinstance(fixture_start_utc, datetime)
            or fixture_start_utc.tzinfo is None
            or type(minimum) is not int or minimum < 1
            or type(require_pace) is not bool or not isinstance(games, list)):
        return {"status": "invalid_input", "usable": False}
    cutoff = fixture_start_utc.astimezone(timezone.utc).timestamp()
    accepted = []
    ids = set()
    for game in games:
        if not isinstance(game, dict):
            return {"status": "invalid_record", "usable": False}
        try:
            gid = game["provider_fixture_id"]
            ts = game["start_ts_utc"]
            home_id = game["home_team_id"]
            away_id = game["away_team_id"]
            home_score = game["actual_home"]
            away_score = game["actual_away"]
        except KeyError:
            return {"status": "invalid_record", "usable": False}
        if (not isinstance(gid, str) or not gid or gid in ids
                or type(ts) not in (int, float) or not 0 < ts < cutoff
                or home_id == away_id or team_id not in (home_id, away_id)
                or type(home_score) is not int or type(away_score) is not int
                or not 0 <= home_score <= 250 or not 0 <= away_score <= 250):
            return {"status": "invalid_record_or_leakage", "usable": False}
        ids.add(gid)
        accepted.append(game)
    if len(accepted) < minimum:
        return {"status": "insufficient_games", "usable": False, "count": len(accepted)}
    # Scoreboard does not supply measured possessions. It is NOT safe to
    # silently turn score-only records into pace-dependent baseline inputs.
    if require_pace:
        return {"status": "pace_unavailable", "usable": False, "count": len(accepted)}
    return {"status": "score_history_verified", "usable": True, "count": len(accepted)}
