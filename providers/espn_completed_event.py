"""Strict parser for ESPN NBA completed game records.

This module parses supplied ESPN event payloads; it does not fetch data.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Dict, Optional


def _parse_final_score(raw: Any) -> Optional[int]:
    """Accept ESPN scalar scores or structured {value, displayValue} scores."""
    if isinstance(raw, dict):
        value = raw.get("value")
        display = raw.get("displayValue")
        if value is None:
            raw = display
        else:
            raw = value
            # Reject contradictory representations rather than guessing.
            if display is not None:
                display_score = _parse_final_score(display)
                value_score = _parse_final_score(value)
                if display_score is None or value_score is None or display_score != value_score:
                    return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        return None
    if isinstance(raw, str) and not raw.strip():
        return None
    try:
        score = float(raw)
    except (ValueError, OverflowError):
        return None
    if not math.isfinite(score) or score < 0 or not score.is_integer():
        return None
    return int(score)


def parse_completed_nba_event(event: Dict[str, Any], now_utc: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    if not isinstance(event, dict):
        return None
    event_id = str(event.get("id") or "").strip()
    if not event_id:
        return None
    try:
        start = datetime.fromisoformat(str(event["date"]).replace("Z", "+00:00"))
        if start.tzinfo is None:
            return None
        start = start.astimezone(timezone.utc)
        now = now_utc or datetime.now(timezone.utc)
        if now.tzinfo is None or start >= now.astimezone(timezone.utc):
            return None
        competitions = event["competitions"]
        if not isinstance(competitions, list) or len(competitions) != 1:
            return None
        competition = competitions[0]
        status = competition["status"]["type"]
        if not isinstance(status, dict):
            return None
        if status.get("state") not in ("post", "completed") or status.get("completed") is not True:
            return None
        competitors = competition["competitors"]
        if not isinstance(competitors, list) or len(competitors) != 2:
            return None
        by_side = {}
        for competitor in competitors:
            side = competitor.get("homeAway")
            team_id = str(competitor.get("team", {}).get("id") or "").strip()
            score = competitor.get("score")
            if side not in ("home", "away") or side in by_side or not team_id:
                return None
            value = _parse_final_score(score)
            if value is None:
                return None
            by_side[side] = (team_id, value)
        if (set(by_side) != {"home", "away"} or by_side["home"][0] == by_side["away"][0]
                or by_side["home"][1] == by_side["away"][1]):
            return None
        return {
            "provider": "ESPN",
            "provider_fixture_id": event_id,
            "start_ts_utc": int(start.timestamp()),
            "home_team_id": by_side["home"][0],
            "away_team_id": by_side["away"][0],
            "actual_home": by_side["home"][1],
            "actual_away": by_side["away"][1],
            "scope": "FINAL_WITH_OT",
        }
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        return None
