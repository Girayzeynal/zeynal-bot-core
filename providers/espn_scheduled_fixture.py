"""Strict, read-only parsing of ESPN NBA scheduled fixture identities.

Does not infer a fixture from team names, fetch data, or persist predictions.
"""
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def parse_scheduled_nba_fixture(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(event, dict):
        return None
    event_id = event.get("id")
    if not isinstance(event_id, str) or not event_id.strip():
        return None
    try:
        start = datetime.fromisoformat(event["date"].replace("Z", "+00:00"))
        if start.tzinfo is None:
            return None
        competitions = event["competitions"]
        if not isinstance(competitions, list) or len(competitions) != 1:
            return None
        competition = competitions[0]
        if not isinstance(competition, dict):
            return None
        status = competition.get("status") or event.get("status")
        if not isinstance(status, dict):
            return None
        status_type = status.get("type")
        if not isinstance(status_type, dict) or status_type.get("state") != "pre" or status_type.get("completed") is not False:
            return None
        competitors = competition.get("competitors")
        if not isinstance(competitors, list) or len(competitors) != 2:
            return None
        sides = {}
        for row in competitors:
            if not isinstance(row, dict):
                return None
            side = row.get("homeAway")
            team = row.get("team")
            tid = team.get("id") if isinstance(team, dict) else None
            if side not in ("home", "away") or side in sides or not isinstance(tid, str) or not tid.strip():
                return None
            sides[side] = tid.strip()
        if set(sides) != {"home", "away"} or sides["home"] == sides["away"]:
            return None
        return {
            "provider": "ESPN",
            "provider_fixture_id": event_id.strip(),
            "start_ts_utc": int(start.astimezone(timezone.utc).timestamp()),
            "home_team_id": sides["home"],
            "away_team_id": sides["away"],
        }
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
        return None
