"""Run a read-only ESPN NBA scoreboard quality smoke check.

Usage: python -m providers.espn_live_smoke 20261031
Exit status: 0 verified response; 1 unavailable or invalid data; 2 bad arguments.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime

from providers.espn_adapter import ESPNAdapter


async def check_scoreboard(date: str) -> dict:
    adapter = ESPNAdapter()
    try:
        report = await adapter.fetch_nba_scoreboard_quality_report(date)
        quality = report["quality"]
        if (
            quality["total_raw"]
            != quality["accepted_unique"] + quality["invalid_or_incomplete"]
               + quality["duplicate_identical"] + quality["conflicting_records"]
        ):
            raise RuntimeError("ESPN quality conservation invariant failed")
        if quality["accepted_unique"] != len(report["completed_events"]):
            raise RuntimeError("ESPN accepted count does not match vetted events")
        identity = quality.get("identity_audit")
        if not isinstance(identity, dict):
            raise RuntimeError("ESPN identity audit is missing")
        for key in (
            "eastern_date_mismatch_fixture_ids",
            "duplicate_fixture_ids",
            "teams_in_multiple_accepted_games",
        ):
            anomalies = identity.get(key)
            if not isinstance(anomalies, list):
                raise RuntimeError("ESPN identity audit is malformed")
            if anomalies:
                raise RuntimeError("ESPN identity anomaly detected")
        return {
            "status": "verified_response",
            "date_yyyymmdd": date,
            "observed_at_utc": report["observed_at_utc"],
            "quality": quality,
            "completed_events_count": len(report["completed_events"]),
            "completed_fixture_ids": sorted(
                event["provider_fixture_id"] for event in report["completed_events"]
            ),
        }
    finally:
        await adapter.aclose()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("Usage: python -m providers.espn_live_smoke YYYYMMDD", file=sys.stderr)
        return 2
    date = args[0]
    try:
        if len(date) != 8 or not date.isascii() or not date.isdigit():
            raise ValueError("invalid date format")
        datetime.strptime(date, "%Y%m%d")
    except ValueError:
        print("Invalid YYYYMMDD calendar date", file=sys.stderr)
        return 2
    try:
        result = asyncio.run(check_scoreboard(date))
    except (RuntimeError, ValueError, OSError) as exc:
        print(json.dumps({"status": "error", "date_yyyymmdd": date,
                          "error_type": type(exc).__name__}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
