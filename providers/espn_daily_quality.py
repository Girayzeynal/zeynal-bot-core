"""Read-only, date-scoped ESPN NBA quality report collection."""
from __future__ import annotations

from typing import Any, Iterable


async def collect_nba_daily_quality(adapter: Any, dates: Iterable[str]) -> dict:
    """Collect daily reports sequentially without writing predictions or outcomes.

    Failed dates are not treated as zero-game dates. The report is limited to
    the exact dates supplied; it is not a complete NBA season coverage metric.
    """
    rows = []
    seen: set[str] = set()
    for date in dates:
        if not isinstance(date, str):
            raise ValueError("dates must be YYYYMMDD strings")
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
