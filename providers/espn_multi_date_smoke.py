"""Read-only multi-day NBA ESPN live smoke, with fail-closed date coverage."""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime

from providers.espn_adapter import ESPNAdapter
from providers.espn_live_smoke import check_scoreboard


async def check_dates(dates: list[str]) -> dict:
    results = []
    seen_fixtures: set[str] = set()
    for date in dates:
        result = await check_scoreboard(date)
        fixture_ids = result.get("completed_fixture_ids")
        if not isinstance(fixture_ids, list) or not all(
            isinstance(value, str) and bool(value) for value in fixture_ids
        ):
            raise RuntimeError("ESPN multi-date fixture identities missing")
        if len(fixture_ids) != result["completed_events_count"]:
            raise RuntimeError("ESPN multi-date fixture count mismatch")
        if len(set(fixture_ids)) != len(fixture_ids):
            raise RuntimeError("ESPN duplicate fixture within a date")
        if seen_fixtures.intersection(fixture_ids):
            raise RuntimeError("ESPN duplicate fixture across dates")
        seen_fixtures.update(fixture_ids)
        results.append(result)
    return {
        "status": "verified_multi_date",
        "dates_checked": len(results),
        "total_raw": sum(r["quality"]["total_raw"] for r in results),
        "accepted_unique": sum(r["quality"]["accepted_unique"] for r in results),
        "daily": results,
    }


def main(argv: list[str] | None = None) -> int:
    dates = list(sys.argv[1:] if argv is None else argv)
    if not 2 <= len(dates) <= 7 or len(set(dates)) != len(dates):
        print("Usage: python -m providers.espn_multi_date_smoke DATE DATE [DATE...] (2-7 unique dates)", file=sys.stderr)
        return 2
    try:
        for date in dates:
            if len(date) != 8 or not date.isascii() or not date.isdigit():
                raise ValueError("invalid date")
            datetime.strptime(date, "%Y%m%d")
    except ValueError:
        print("Invalid YYYYMMDD calendar date", file=sys.stderr)
        return 2
    try:
        result = asyncio.run(check_dates(dates))
    except (RuntimeError, ValueError, OSError) as exc:
        print(json.dumps({"status": "error", "error_type": type(exc).__name__}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
