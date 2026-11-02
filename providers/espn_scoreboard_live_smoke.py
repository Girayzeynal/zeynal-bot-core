"""Manual read-only ESPN scoreboard smoke test.

Usage: python3 -m providers.espn_scoreboard_live_smoke 20261031
No API key, deployment, or predictions. Exit nonzero if the date has no
verified final games or the response cannot be trusted.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from providers.espn_completed_event import parse_completed_nba_event

BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"


def run(day: str) -> int:
    try:
        date = datetime.strptime(day, "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        print(json.dumps({"status": "invalid_date"}))
        return 2
    if date.date() >= datetime.now(timezone.utc).date():
        print(json.dumps({"status": "not_historical"}))
        return 2
    url = BASE + "?dates=" + day
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "zeynal-scoreboard-diagnostic/1.0"})
        with urllib.request.urlopen(req, timeout=15) as response:
            if response.status != 200:
                raise ValueError("unexpected_http_status")
            payload = json.load(response)
        events = payload["events"]
        if not isinstance(events, list):
            raise ValueError("invalid_events")
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "request_or_schema_error", "error": type(exc).__name__}))
        return 1
    cutoff = datetime.now(timezone.utc)
    accepted = {}
    conflicts = set()
    for event in events:
        record = parse_completed_nba_event(event, cutoff)
        if record is None:
            continue
        key = record["provider_fixture_id"]
        if key in conflicts:
            continue
        if key in accepted and accepted[key] != record:
            conflicts.add(key)
            accepted.pop(key, None)
        else:
            accepted[key] = record
    teams = {}
    for record in accepted.values():
        for key, score_key in (("home_team_id", "actual_home"), ("away_team_id", "actual_away")):
            team = record[key]
            teams[team] = teams.get(team, 0) + 1
    result = {
        "date": day, "provider": "ESPN",
        "raw_events": len(events), "verified_final_games": len(accepted),
        "conflicting_ids": len(conflicts), "teams_with_verified_games": len(teams),
        "status": "pass" if accepted else "insufficient_or_invalid",
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if accepted else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 -m providers.espn_scoreboard_live_smoke YYYYMMDD")
        raise SystemExit(2)
    raise SystemExit(run(sys.argv[1]))
