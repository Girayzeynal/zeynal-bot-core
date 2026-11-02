"""Read-only ESPN season metadata audit.

Run: python3 -m providers.espn_season_live_smoke 20261017 20261031
Reports only metadata distributions, not betting predictions.
"""
import asyncio
import json
import sys
from collections import Counter

from providers.espn_scoreboard_history import ESPNScoreboardHistory
from providers.espn_season_filter import is_explicit_regular_season


async def audit(days):
    adapter = ESPNScoreboardHistory()
    try:
        out = []
        for day in days:
            if len(day) != 8 or not day.isascii() or not day.isdigit():
                out.append({"date": day, "status": "invalid_date"})
                continue
            events = await adapter._fetch_day(day)
            if events is None:
                out.append({"date": day, "status": "unavailable"})
                continue
            types = Counter()
            regular = 0
            for event in events:
                season = event.get("season") if isinstance(event, dict) else None
                kind = season.get("type") if isinstance(season, dict) else None
                types[str(kind)] += 1
                if is_explicit_regular_season(event) is True:
                    regular += 1
            out.append({
                "date": day, "status": "pass",
                "raw_events": len(events),
                "regular_season_candidates": regular,
                "season_types": dict(types),
            })
        print(json.dumps({"provider": "ESPN", "results": out}, indent=2))
        return 0 if all(x["status"] == "pass" for x in out) else 1
    finally:
        await adapter.aclose()


if __name__ == "__main__":
    days = sys.argv[1:]
    if not 1 <= len(days) <= 4:
        print("Usage: python3 -m providers.espn_season_live_smoke YYYYMMDD [YYYYMMDD ...]")
        raise SystemExit(2)
    raise SystemExit(asyncio.run(audit(days)))
