"""Offline-first NBA fixture audit: saved MoviOdds catalog vs ESPN schedule.

No MoviOdds request, no MoviOdds key, no production or archive writes.
Only --live enables read-only ESPN fixture requests. No results are invented.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
from urllib.error import URLError
from urllib.request import Request, build_opener
from zoneinfo import ZoneInfo

from hybrid_engine.movi_bulk_pilot import NoRedirect, utc_time

TZ = ZoneInfo("Europe/Istanbul")
NY = ZoneInfo("America/New_York")
BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
SIZE_LIMIT = 4 * 1024 * 1024
CANONICAL = {
    "ATL": "Atlanta Hawks", "BOS": "Boston Celtics",
    "BKN": "Brooklyn Nets", "CHA": "Charlotte Hornets",
    "CHI": "Chicago Bulls", "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks", "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons", "GSW": "Golden State Warriors",
    "HOU": "Houston Rockets", "IND": "Indiana Pacers",
    "LAC": "LA Clippers", "LAL": "Los Angeles Lakers",
    "MEM": "Memphis Grizzlies", "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks", "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans", "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder", "ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers", "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers", "SAC": "Sacramento Kings",
    "SAS": "San Antonio Spurs", "TOR": "Toronto Raptors",
    "UTA": "Utah Jazz", "WAS": "Washington Wizards",
}
ALTERNATE = {
    "NOP": ("NO Pelicans",),
    "NYK": ("NY Knicks",),
    "SAS": ("SA Spurs",),
    "GSW": ("GS Warriors",),
    "LAL": ("LA Lakers",),
    "LAC": ("LA Clippers",),
    "UTA": ("UT Jazz",),
    "POR": ("POR Trail Blazers",),
    "WAS": ("WSH Wizards",),
}


def norm(value):
    return re.sub(r"[^a-z0-9]", "", value.lower()) if isinstance(value, str) else ""


TEAM_LOOKUP = {}
for code, name in CANONICAL.items():
    candidates = (name, code, f"{code} {name.split()[-1]}", *ALTERNATE.get(code, ()))
    for item in candidates:
        TEAM_LOOKUP[norm(item)] = code
TEAM_LOOKUP[norm("Philadelphia Sixers")] = "PHI"


def code_of(name):
    return TEAM_LOOKUP.get(norm(name))


def parse_espn_board(doc, start_day, end_day):
    if not isinstance(doc, dict) or not isinstance(doc.get("events"), list):
        raise ValueError("ESPN_SCHEDULE_BAD_SCHEMA")
    result = {}
    for event in doc["events"][:100]:
        if not isinstance(event, dict):
            continue
        fixture_id = event.get("id")
        tip = utc_time(event.get("date"))
        competitions = event.get("competitions")
        if not isinstance(fixture_id, (str, int)) or tip is None or not isinstance(competitions, list) or len(competitions) != 1:
            continue
        local_day = tip.astimezone(TZ).date()
        if not start_day <= local_day <= end_day:
            continue
        competitors = competitions[0].get("competitors") if isinstance(competitions[0], dict) else None
        if not isinstance(competitors, list) or len(competitors) != 2:
            continue
        teams = {}
        for side in competitors:
            if not isinstance(side, dict) or side.get("homeAway") not in ("home", "away"):
                break
            team = side.get("team")
            if not isinstance(team, dict):
                break
            code = team.get("abbreviation", "").upper()
            if code == "WSH":
                code = "WAS"
            if code not in CANONICAL:
                code = code_of(team.get("displayName")) or ""
            if code not in CANONICAL:
                break
            teams[side["homeAway"]] = code
        if set(teams) != {"home", "away"}:
            continue
        result[str(fixture_id)] = {
            "id": str(fixture_id), "date_tsi": local_day.isoformat(),
            "start_tsi": tip.astimezone(TZ).strftime("%d.%m.%Y %H:%M"),
            "start_utc": tip.isoformat(),
            **teams,
        }
    return result


def compare_cached(cached, boards):
    if (not isinstance(cached, dict) or cached.get("league") != "NBA"
            or not isinstance(cached.get("days"), dict)
            or not isinstance(cached.get("start_day_tsi"), str)
            or not isinstance(cached.get("end_day_tsi"), str)):
        return {"status": "INVALID_MOVIODDS_CACHE"}
    start_day = date.fromisoformat(cached["start_day_tsi"])
    end_day = date.fromisoformat(cached["end_day_tsi"])
    if (end_day - start_day).days != 6:
        return {"status": "INVALID_WEEK_RANGE"}
    official = {}
    for doc in boards:
        for id_, g in parse_espn_board(doc, start_day, end_day).items():
            if id_ in official and official[id_] != g:
                raise ValueError("ESPN_FIXTURE_CONFLICT")
            official[id_] = g
    provider = {}
    for day, events in cached["days"].items():
        if not isinstance(events, list):
            continue
        for ev in events:
            if not isinstance(ev, dict) or ev.get("tsi", "")[:10] != date.fromisoformat(day).strftime("%d.%m.%Y"):
                continue
            home, away = code_of(ev.get("home")), code_of(ev.get("away"))
            stamp = utc_time(ev.get("utc"))
            if not home or not away or not stamp:
                continue
            key = (day, home, away)
            if key in provider:
                raise ValueError("MOVI_DUPLICATE_MATCHUP")
            provider[key] = ev
    mismatches = []
    missing = {}
    counts = {str(start_day + timedelta(days=i)): {
        "espn": 0, "moviodds_matched": 0, "not_in_moviodds_catalog": 0
    } for i in range(7)}
    for fixture in sorted(official.values(), key=lambda x: x["start_utc"]):
        day = fixture["date_tsi"]
        counts[day]["espn"] += 1
        match = provider.get((day, fixture["home"], fixture["away"]))
        if match is None:
            counts[day]["not_in_moviodds_catalog"] += 1
            missing.setdefault(day, []).append({
                "start_tsi": fixture["start_tsi"],
                "away": CANONICAL[fixture["away"]],
                "home": CANONICAL[fixture["home"]],
            })
        else:
            counts[day]["moviodds_matched"] += 1
            diff = round((utc_time(match["utc"]) -
                          utc_time(fixture["start_utc"])).total_seconds() / 60, 1)
            if diff != 0:
                mismatches.append({"date_tsi": day, "matchup":
                    CANONICAL[fixture["away"]] + " @ " + CANONICAL[fixture["home"]],
                    "espn_tsi": fixture["start_tsi"],
                    "moviodds_tsi": match["tsi"], "difference_minutes": diff})
    return {
        "status": "OK",
        "week_tsi": [start_day.isoformat(), end_day.isoformat()],
        "official_fixtures": len(official),
        "provider_fixture_rows": len(provider),
        "matched": sum(x["moviodds_matched"] for x in counts.values()),
        "time_differences": mismatches[:60],
        "day_summary": counts,
        "missing_from_provider_examples": {day: games[:4] for day, games in missing.items()},
        "warning": "MoviOdds catalog listing is NOT the same as official NBA fixture coverage or live odds."
    }


def fetch_espn_day(day):
    url = BASE + "?dates=" + day.strftime("%Y%m%d") + "&limit=1000"
    request = Request(url, headers={"Accept": "application/json",
                                   "User-Agent": "ZEYNAL-TestOnly-NBAFixture/1"})
    with build_opener(NoRedirect()).open(request, timeout=15) as response:
        if response.status != 200 or response.headers.get_content_type() != "application/json":
            raise ValueError("ESPN_BAD_HTTP_RESPONSE")
        body = response.read(SIZE_LIMIT + 1)
        if len(body) > SIZE_LIMIT:
            raise ValueError("ESPN_TOO_LARGE")
        return json.loads(body)


def main():
    parser = argparse.ArgumentParser(description="Compare saved MoviOdds week with ESPN fixture dates")
    parser.add_argument("--cached", default="nba_week_21_27.json")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not args.live:
        print(json.dumps({"status": "OFFLINE_ONLY", "network_calls": 0}))
        return
    cache_path = Path(args.cached)
    if not cache_path.is_file() or cache_path.stat().st_size > SIZE_LIMIT:
        print(json.dumps({"status": "CACHE_MISSING_OR_OVERSIZE", "network_calls": 0}))
        return
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        start_day = date.fromisoformat(cached["start_day_tsi"])
        end_day = date.fromisoformat(cached["end_day_tsi"])
        if (end_day - start_day).days != 6:
            raise ValueError("INVALID_CACHE_DATES")
        # A local TSİ day can contain fixtures from the previous US/Eastern date.
        first_us_day = (datetime.combine(start_day, datetime.min.time(), tzinfo=TZ)
                        - timedelta(hours=8)).astimezone(NY).date()
        # Fetch eight Eastern calendar days, then keep exact Turkish dates.
        boards = [fetch_espn_day(first_us_day + timedelta(days=i))
                  for i in range(8)]
        result = compare_cached(cached, boards)
        result["network_calls_espn"] = 8
        result["network_calls_moviodds"] = 0
    except (URLError, OSError, ValueError, TypeError, KeyError,
            json.JSONDecodeError):
        result = {"status": "ESPN_COMPARISON_UNAVAILABLE",
                  "network_calls_moviodds": 0,
                  "note": "Partial ESPN calls possible; no coverage claimed."}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
