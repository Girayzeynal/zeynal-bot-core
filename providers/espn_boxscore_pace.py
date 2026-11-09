"""Auditable box-score possession estimate, not measured play-by-play pace.

Possessions per team = FGA + 0.44 * FTA - ORB + total TOV.
Pace = mean(team possessions) * 48 / (48 + 5 * overtime periods).
The 0.44 coefficient is a modeling assumption, never a provider observation.
Missing/contradictory identity, score, duration or inputs reject the estimate.
"""
from __future__ import annotations

from datetime import datetime
import re

from providers.espn_completed_event import parse_completed_nba_event

METHOD = "ESPN_BOXSCORE_POSSESSIONS_044_V1"


def _count(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,3}", value):
        raise ValueError("Missing or malformed box-score count")
    return int(value)


def _shots(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,3}-[0-9]{1,3}", value):
        raise ValueError("Missing or malformed shot totals")
    made, attempted = map(int, value.split("-"))
    if made > attempted:
        raise ValueError("Made shots exceed attempts")
    return made, attempted


def estimate_pace_from_summary(payload: dict, game: dict,
                               now_utc: datetime | None = None) -> dict | None:
    """Reconcile an ESPN summary with a parsed scoreboard row before deriving pace.

    Returns inputs, method, duration and estimated pace; None on uncertainty.
    No network calls or storage writes. Caller authenticates the source endpoint.
    """
    try:
        header = payload["header"]
        competitions = header["competitions"]
        if len(competitions) != 1:
            return None
        competition = competitions[0]
        event = dict(header, date=competition["date"])
        parsed = parse_completed_nba_event(event, now_utc)
        fields = ("provider", "provider_fixture_id", "start_ts_utc", "home_team_id",
                  "away_team_id", "actual_home", "actual_away", "scope")
        if parsed is None or any(parsed[k] != game.get(k) for k in fields):
            return None
        if (header.get("season", {}).get("type") != 2
                or competition.get("id") != game["provider_fixture_id"]):
            return None
        fmt = payload["format"]
        if (fmt["regulation"]["periods"] != 4 or fmt["regulation"]["clock"] != 720
                or fmt["overtime"]["clock"] != 300):
            return None
        # Summary finals may omit status.period. Both full period-score arrays
        # still provide explicit duration evidence; never assume four periods.
        periods = len(competition["competitors"][0]["linescores"])
        if type(periods) is not int or not 4 <= periods <= 12:
            return None
        stated_period = competition["status"].get("period")
        if stated_period is not None and (type(stated_period) is not int or stated_period != periods):
            return None
        for competitor in competition["competitors"]:
            lines = competitor["linescores"]
            if len(lines) != periods or sum(_count(p["displayValue"]) for p in lines) != int(competitor["score"]):
                return None
        teams = payload["boxscore"]["teams"]
        if not isinstance(teams, list) or len(teams) != 2:
            return None
        inputs = {}
        for team in teams:
            side = team["homeAway"]
            if side not in ("home", "away") or side in inputs:
                return None
            if team["team"]["id"] != game[f"{side}_team_id"]:
                return None
            stats = {}
            for item in team["statistics"]:
                name = item["name"]
                if name in stats:
                    return None
                stats[name] = item["displayValue"]
            fgm, fga = _shots(stats["fieldGoalsMade-fieldGoalsAttempted"])
            ftm, fta = _shots(stats["freeThrowsMade-freeThrowsAttempted"])
            tpm, tpa = _shots(stats["threePointFieldGoalsMade-threePointFieldGoalsAttempted"])
            orb = _count(stats["offensiveRebounds"])
            tov = _count(stats["totalTurnovers"])
            if (tpm > fgm or tpa > fga or orb > fga - fgm + fta - ftm
                    or 2 * fgm + tpm + ftm != game[f"actual_{side}"]):
                return None
            possessions = fga + 0.44 * fta - orb + tov
            if possessions <= 0:
                return None
            inputs[side] = dict(fga=fga, fta=fta, orb=orb, total_turnovers=tov,
                                estimated_possessions=possessions)
        minutes = 48 + 5 * (periods - 4)
        pace = sum(v["estimated_possessions"] for v in inputs.values()) / 2 * 48 / minutes
        return dict(method=METHOD, kind="BOX_SCORE_ESTIMATE", pace=pace,
                    duration_minutes=minutes, inputs=inputs,
                    provider_fixture_id=game["provider_fixture_id"],
                    source_url="https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event="
                               + game["provider_fixture_id"])
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return None
