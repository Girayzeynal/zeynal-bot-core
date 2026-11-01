"""Read-only diagnostic categorization for rejected ESPN NBA event records.

Categories are diagnostic hints; acceptance remains controlled by the strict
parse_completed_nba_event parser. Never log full raw payloads.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def rejected_event_reason(raw: Any, observed_at_utc: int) -> str:
    if not isinstance(raw, dict):
        return "invalid_event_structure"
    if not str(raw.get("id") or "").strip():
        return "missing_fixture_id"
    date = raw.get("date")
    try:
        start = datetime.fromisoformat(str(date).replace("Z", "+00:00"))
        if start.tzinfo is None:
            return "invalid_start_time"
        start = start.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return "invalid_start_time"
    if start.timestamp() >= observed_at_utc:
        return "future_or_not_started"
    competitions = raw.get("competitions")
    if not isinstance(competitions, list) or len(competitions) != 1:
        return "invalid_competitions"
    competition = competitions[0]
    if not isinstance(competition, dict):
        return "invalid_competitions"
    status = competition.get("status")
    if not isinstance(status, dict) or not isinstance(status.get("type"), dict):
        return "missing_competition_status"
    kind = status["type"]
    if kind.get("state") != "completed" or kind.get("completed") is not True:
        return "not_completed"
    competitors = competition.get("competitors")
    if not isinstance(competitors, list) or len(competitors) != 2:
        return "invalid_competitors"
    by_side = {}
    for competitor in competitors:
        if not isinstance(competitor, dict):
            return "invalid_competitors"
        side = competitor.get("homeAway")
        team = competitor.get("team")
        team_id = str(team.get("id") or "").strip() if isinstance(team, dict) else ""
        if side not in ("home", "away") or side in by_side or not team_id:
            return "invalid_team_identity"
        try:
            import math
            score = competitor.get("score")
            if isinstance(score, bool):
                return "invalid_score"
            value = float(score)
            if not math.isfinite(value) or value < 0 or not value.is_integer():
                return "invalid_score"
        except (TypeError, ValueError, OverflowError):
            return "invalid_score"
        by_side[side] = team_id
    if set(by_side) != {"home", "away"} or by_side["home"] == by_side["away"]:
        return "invalid_team_identity"
    return "unclassified_parser_rejection"
