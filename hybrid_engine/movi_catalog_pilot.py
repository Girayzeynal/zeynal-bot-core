"""Read-only MoviOdds basketball catalog pilot; NOT integrated into production.

Only explicit --live + ZEYNAL_MOVIODDS_ENABLED=1 + private env key may
make one authenticated call to the official fixed HTTPS /catalog endpoint.
The odds board and forecast/archives are left untouched.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import gzip
import io
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener
from zoneinfo import ZoneInfo

from hybrid_engine.movi_bulk_pilot import (
    MAX_COMPRESSED, MAX_JSON, NoRedirect, classify_http_error,
    league_id, utc_time,
)

CATALOG_URL = "https://moviodds.com/catalog?sport=basketball"
ISTANBUL = ZoneInfo("Europe/Istanbul")
TARGETS = ("NBA", "EUROLEAGUE", "EUROCUP")


def propose_odds_slots(upcoming: dict, now: datetime) -> list[dict]:
    """Dry-run only: at most 4 regular odds pulls/day + 1 catalog + 1 reserve.

    The calendar poll and the odds pulls are separate provider requests.
    A proposal does not create a background task or consume quota.
    """
    candidates = {}
    for fixtures in upcoming.values():
        for kickoff, _ in fixtures:
            # A pre-match check at T-20 minutes, not after the event starts.
            proposed = kickoff - timedelta(minutes=20)
            if proposed <= now:
                continue
            local = proposed.astimezone(ISTANBUL)
            candidates.setdefault(local.date(), []).append(local)
    schedule = []
    for day, timestamps in sorted(candidates.items()):
        moments = sorted(set(timestamps))
        slots = []
        baseline = datetime.combine(day, datetime.min.time(), tzinfo=ISTANBUL).replace(
            hour=10, minute=30
        )
        if baseline > now.astimezone(ISTANBUL) and baseline < moments[0]:
            slots.append(baseline)
        skipped = 0
        for moment in moments:
            if any(abs(moment - prior) < timedelta(minutes=80) for prior in slots):
                continue
            if len(slots) >= 4:
                skipped += 1
                continue
            slots.append(moment)
        if slots:
            schedule.append({
                "tsi_day": day.isoformat(),
                "regular_odds_slots_tsi": [
                    item.strftime("%Y-%m-%d %H:%M") for item in sorted(slots)
                ],
                "catalog_calls_per_day": 1,
                "regular_odds_calls": len(slots),
                "emergency_odds_reserve": 1,
                "max_total_calls_including_reserve": 2 + len(slots),
                "uncovered_80_min_clusters": skipped,
            })
    return schedule


def inspect_catalog(data: dict, now: datetime | None = None) -> dict:
    """Never confuse an empty catalog / premarket week with unsupported league."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not isinstance(data, dict) or not isinstance(data.get("fixtures"), list):
        return {"status": "BAD_SCHEMA", "leagues": {}, "unclassified_europe": []}
    result = {
        "status": "WARMING" if data.get("warming") is True else "OK",
        "source": "MOVIODDS_CATALOG_NOT_ODDS",
        "horizon_days": 7,
        "leagues": {name: {
            "listed_total": 0, "next_7_days": 0, "after_7_days": 0,
            "next_tsi": [], "unverified_kickoff": 0
        } for name in TARGETS},
        "unclassified_europe": [],
        "catalog_rows_examined": min(5000, len(data["fixtures"])),
        "truncated_catalog_rows": max(0, len(data["fixtures"]) - 5000),
    }
    seen = set()
    upcoming = {name: [] for name in TARGETS}
    for fixture in data["fixtures"][:5000]:
        if not isinstance(fixture, dict):
            continue
        if fixture.get("sport") not in (None, "basketball"):
            continue
        source_league = fixture.get("league")
        competition = league_id(source_league)
        if competition is None:
            if (isinstance(source_league, str) and
                    ("euro" in source_league.lower() or "nba" in source_league.lower()) and
                    len(result["unclassified_europe"]) < 30 and
                    source_league not in result["unclassified_europe"]):
                result["unclassified_europe"].append(source_league[:90])
            continue
        uid = fixture.get("id")
        if not isinstance(uid, (int, str)) or not str(uid).strip():
            continue
        identity = (competition, str(uid))
        if identity in seen:
            continue
        seen.add(identity)
        info = result["leagues"][competition]
        info["listed_total"] += 1
        kickoff = utc_time(fixture.get("kickoff_utc"))
        if kickoff is None:
            info["unverified_kickoff"] += 1
            continue
        if fixture.get("in_play") is True or kickoff <= now:
            continue
        if kickoff <= now + timedelta(days=7):
            info["next_7_days"] += 1
            upcoming[competition].append((kickoff, str(uid)))
        else:
            info["after_7_days"] += 1
    for competition in TARGETS:
        info = result["leagues"][competition]
        info["next_tsi"] = [
            dt.astimezone(ISTANBUL).strftime("%Y-%m-%d %H:%M %z")
            for dt, _ in sorted(upcoming[competition])[:8]
        ]
    result["dry_run_schedule"] = propose_odds_slots(upcoming, now)
    result["schedule_status"] = "PROPOSAL_ONLY_NOT_INSTALLED"
    result["coverage_statement"] = (
        "Catalog listing is not proof of a current bet365 price; zero "
        "fixtures is not proof that a league is unsupported."
    )
    return result


def read_catalog(key: str) -> dict:
    req = Request(CATALOG_URL, headers={
        "X-API-Key": key, "Accept": "application/json",
        "Accept-Encoding": "gzip", "User-Agent": "ZEYNAL-TestOnly-Catalog/1",
    })
    with build_opener(NoRedirect()).open(req, timeout=20) as response:
        if response.status != 200 or response.headers.get_content_type() != "application/json":
            raise ValueError("BAD_CATALOG_RESPONSE")
        raw = response.read(MAX_COMPRESSED + 1)
        if len(raw) > MAX_COMPRESSED:
            raise ValueError("COMPRESSED_CATALOG_TOO_LARGE")
        if response.headers.get("Content-Encoding", "").lower() == "gzip":
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as decompressed:
                raw = decompressed.read(MAX_JSON + 1)
        if len(raw) > MAX_JSON:
            raise ValueError("CATALOG_TOO_LARGE")
        return json.loads(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description="One-request 7-day MoviOdds basketball catalog test")
    parser.add_argument("--live", action="store_true")
    opts = parser.parse_args()
    key = os.getenv("ZEYNAL_MOVIODDS_KEY", "")
    if not opts.live:
        report = {"status": "OFFLINE_ONLY", "network_calls": 0}
    elif os.getenv("ZEYNAL_MOVIODDS_ENABLED") != "1" or not key:
        report = {"status": "NOT_AUTHORIZED", "network_calls": 0}
    else:
        try:
            report = inspect_catalog(read_catalog(key))
            report["network_calls"] = 1
        except HTTPError as exc:
            status = exc.code
            reason = classify_http_error(exc)
            exc.close()
            report = {"status": "HTTP_ERROR", "http_status": status,
                      "error_category": reason, "network_calls": 1}
        except (URLError, OSError, ValueError, TypeError, json.JSONDecodeError):
            report = {"status": "SOURCE_UNAVAILABLE", "network_calls": 1}
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
