"""MoviOdds test-only NBA catalog: rolling 7 TSİ dates, one request.

Explicitly opt-in to a SINGLE live GET /catalog?sport=basketball.
No archives, probabilities, odds settlement, bot wiring or background jobs.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

from hybrid_engine.movi_bulk_pilot import classify_http_error, league_id, utc_time
from hybrid_engine.movi_catalog_pilot import read_catalog

ISTANBUL = ZoneInfo("Europe/Istanbul")


def nba_week_catalog(data: dict, now: datetime | None = None) -> dict:
    current = (now or datetime.now(timezone.utc)).astimezone(ISTANBUL)
    start_day = current.date()
    final_day = start_day + timedelta(days=6)
    result = {
        "source": "MOVIODDS_CATALOG_BASKETBALL",
        "league": "NBA",
        "timezone": "Europe/Istanbul",
        "start_day_tsi": start_day.isoformat(),
        "end_day_tsi": final_day.isoformat(),
        "status": "OK",
        "total_nba_catalog_entries": 0,
        "upcoming_this_week": 0,
        "days": {str(start_day + timedelta(days=i)): [] for i in range(7)},
        "unclassified_nba_names": [],
        "note": "An empty week can mean fixtures are not yet published by the provider.",
        "network_calls": 0,
    }
    if not isinstance(data, dict) or not isinstance(data.get("fixtures"), list):
        result["status"] = "BAD_SCHEMA"
        return result
    result["status"] = "WARMING" if data.get("warming") is True else "OK"
    seen = set()
    for fixture in data["fixtures"][:10000]:
        if not isinstance(fixture, dict):
            continue
        source_name = fixture.get("league")
        if league_id(source_name) != "NBA":
            if (isinstance(source_name, str) and "nba" in source_name.lower()
                    and source_name not in result["unclassified_nba_names"]
                    and len(result["unclassified_nba_names"]) < 20):
                result["unclassified_nba_names"].append(source_name[:80])
            continue
        if fixture.get("sport") not in (None, "basketball"):
            continue
        identity = fixture.get("id")
        if not isinstance(identity, (str, int)) or not str(identity).strip():
            continue
        fixture_id = str(identity)
        if fixture_id in seen:
            continue
        seen.add(fixture_id)
        result["total_nba_catalog_entries"] += 1
        kickoff = utc_time(fixture.get("kickoff_utc"))
        home, away = fixture.get("home"), fixture.get("away")
        if (kickoff is None or kickoff <= current.astimezone(timezone.utc)
                or fixture.get("in_play") is not False
                or not all(isinstance(v, str) and v.strip() for v in (home, away))):
            continue
        tsi = kickoff.astimezone(ISTANBUL)
        if not start_day <= tsi.date() <= final_day:
            continue
        result["days"][tsi.date().isoformat()].append({
            "tsi": tsi.strftime("%d.%m.%Y %H:%M"),
            "utc": kickoff.isoformat(),
            "away": away.strip(),
            "home": home.strip(),
            "fixture_id": fixture_id,
        })
    for fixtures in result["days"].values():
        fixtures.sort(key=lambda row: (row["utc"], row["fixture_id"]))
    result["upcoming_this_week"] = sum(len(x) for x in result["days"].values())
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Single-call NBA schedule, today + 6 TSİ days")
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args()
    if not args.live:
        report = {"status": "OFFLINE_ONLY", "network_calls": 0}
    elif os.getenv("ZEYNAL_MOVIODDS_ENABLED") != "1" or not os.getenv("ZEYNAL_MOVIODDS_KEY"):
        report = {"status": "NOT_AUTHORIZED", "network_calls": 0}
    else:
        try:
            report = nba_week_catalog(read_catalog(os.environ["ZEYNAL_MOVIODDS_KEY"]))
            report["network_calls"] = 1
        except HTTPError as exc:
            status, category = exc.code, classify_http_error(exc)
            exc.close()
            report = {"status": "HTTP_ERROR", "http_status": status,
                      "error_category": category, "network_calls": 1}
        except (ValueError, TypeError, OSError, URLError, json.JSONDecodeError):
            report = {"status": "SOURCE_UNAVAILABLE", "network_calls": 1}
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
