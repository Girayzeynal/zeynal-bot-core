"""Read-only ESPN scoreboard identity and schedule-date diagnostics.

ESPN NBA scoreboard dates follow the US Eastern schedule calendar rather than
the UTC date. These checks flag suspicious rows; they do not silently rewrite
fixture IDs or exclude valid cross-midnight games.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any


def audit_scoreboard_identity(events: list[dict[str, Any]], date_yyyymmdd: str) -> dict:
    expected = datetime.strptime(date_yyyymmdd, "%Y%m%d").date()
    eastern = ZoneInfo("America/New_York")
    mismatched_ids: list[str] = []
    team_occurrences: Counter[str] = Counter()
    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()
    for event in events:
        fixture_id = event["provider_fixture_id"]
        if fixture_id in seen_ids:
            duplicate_ids.add(fixture_id)
        seen_ids.add(fixture_id)
        start_eastern = datetime.fromtimestamp(
            event["start_ts_utc"], tz=timezone.utc
        ).astimezone(eastern)
        if start_eastern.date() != expected:
            mismatched_ids.append(fixture_id)
        team_occurrences[event["home_team_id"]] += 1
        team_occurrences[event["away_team_id"]] += 1
    return {
        "eastern_date_mismatch_fixture_ids": sorted(set(mismatched_ids)),
        "duplicate_fixture_ids": sorted(duplicate_ids),
        "teams_in_multiple_accepted_games": sorted(
            team_id for team_id, count in team_occurrences.items() if count > 1
        ),
    }
