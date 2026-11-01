"""Read-only, date-scoped ESPN NBA quality report collection."""
from __future__ import annotations

from typing import Any, Iterable
from datetime import datetime


async def collect_nba_daily_quality(adapter: Any, dates: Iterable[str]) -> dict:
    """Collect daily reports sequentially without writing predictions or outcomes.

    Failed dates are not treated as zero-game dates. The report is limited to
    the exact dates supplied; it is not a complete NBA season coverage metric.
    """
    if isinstance(dates, (str, bytes)):
        raise ValueError("dates must be an iterable of YYYYMMDD strings")
    rows = []
    seen: set[str] = set()
    for date in dates:
        if (not isinstance(date, str) or len(date) != 8
                or not date.isascii() or not date.isdigit()):
            raise ValueError("dates must be YYYYMMDD strings")
        try:
            datetime.strptime(date, "%Y%m%d")
        except ValueError as exc:
            raise ValueError("invalid calendar date") from exc
        if date in seen:
            continue
        seen.add(date)
        try:
            result = await adapter.fetch_nba_scoreboard_quality_report(date)
        except (RuntimeError, ValueError) as exc:
            rows.append({
                "date_yyyymmdd": date,
                "status": "fetch_or_validation_error",
                "error_type": type(exc).__name__,
                "quality": None,
            })
            continue
        quality = result.get("quality") if isinstance(result, dict) else None
        keys = (
            "total_raw", "accepted_unique", "invalid_or_incomplete",
            "unfinished_events", "malformed_or_unverifiable_events",
            "duplicate_identical", "conflicting_records",
        )
        valid = (
            isinstance(quality, dict)
            and all(type(quality.get(key)) is int and quality[key] >= 0 for key in keys)
        )
        if valid:
            valid = (
                quality["invalid_or_incomplete"]
                == quality["unfinished_events"] + quality["malformed_or_unverifiable_events"]
                and quality["total_raw"]
                == quality["invalid_or_incomplete"] + quality["accepted_unique"]
                   + quality["duplicate_identical"] + quality["conflicting_records"]
            )
        if not valid:
            rows.append({
                "date_yyyymmdd": date,
                "status": "invalid_quality_report",
                "error_type": "QualityInvariantError",
                "quality": None,
            })
            continue
        rows.append({
            "date_yyyymmdd": date,
            "status": "ok",
            "error_type": None,
            "quality": result["quality"],
        })
    successes = [row for row in rows if row["status"] == "ok"]
    return {
        "dates_requested": len(rows),
        "dates_successful": len(successes),
        "dates_failed": len(rows) - len(successes),
        "raw_events_successful_dates": sum(
            row["quality"]["total_raw"] for row in successes
        ),
        "accepted_unique_successful_dates": sum(
            row["quality"]["accepted_unique"] for row in successes
        ),
        "daily": rows,
    }
