"""Strict offline import of an already verified NBA week console audit.

Consumes only user's locally saved text report; no HTTP, credentials, model writes,
or predictions. The generated snapshot inherits the source report's observation
time and must NOT be represented as a live refreshed fixture feed.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re
import tempfile
from zoneinfo import ZoneInfo

from hybrid_engine.movi_nba_espn_week import code_of

TSI = ZoneInfo("Europe/Istanbul")
DAY_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) \(TSI\) \| ESPN MAC: (\d+)\s*$")
GAME_RE = re.compile(
    r"^(\d\d:\d\d) (.+?) @ (.+?) \[(M\+|M-)\]"
    r"(?: \| MOVI_SAAT_FARKI:([-+]?\d+(?:\.\d+)?)dk)?\s*$"
)
WEEK_RE = re.compile(r"^HAFTA \(TSI\): (\d{4}-\d\d-\d\d) - (\d{4}-\d\d-\d\d)$")
COUNT_RE = re.compile(
    r"^NBA TOPLAM: (\d+) \| MOVIODDS KATALOG ESLESME: (\d+)"
    r" \| KATALOGDA OLMAYAN: (\d+)$"
)


def import_saved_report(raw: str) -> dict:
    """Reject partial, malformed or mismatched saved outputs rather than guessing."""
    if not isinstance(raw, str) or len(raw) > 2_000_000:
        raise ValueError("BAD_REPORT_SIZE")
    lines = raw.splitlines()
    if "DURUM: OK" not in lines:
        raise ValueError("UNVERIFIED_REPORT_STATUS")
    week = next((WEEK_RE.fullmatch(x) for x in lines if x.startswith("HAFTA (TSI): ")), None)
    total = next((COUNT_RE.fullmatch(x) for x in lines if x.startswith("NBA TOPLAM: ")), None)
    if week is None or total is None:
        raise ValueError("MISSING_REPORT_HEADERS")
    first, last = date.fromisoformat(week.group(1)), date.fromisoformat(week.group(2))
    if last - first != timedelta(days=6):
        raise ValueError("WEEK_RANGE_NOT_SEVEN_DAYS")
    expected_games, expected_yes, expected_no = map(int, total.groups())
    if expected_games != expected_yes + expected_no or expected_games > 150:
        raise ValueError("INVALID_REPORT_TOTALS")
    day_counts = {}
    result = []
    seen = set()
    active_day = None
    for line in lines:
        day = DAY_RE.fullmatch(line)
        if day:
            active_day = date.fromisoformat(day.group(1))
            if not first <= active_day <= last or active_day in day_counts:
                raise ValueError("INVALID_OR_DUPLICATE_REPORT_DAY")
            day_counts[active_day] = int(day.group(2))
            continue
        row = GAME_RE.fullmatch(line)
        if row is None:
            continue
        if active_day is None:
            raise ValueError("GAME_WITHOUT_DAY")
        hhmm, away_name, home_name, market_flag, delta_text = row.groups()
        away, home = code_of(away_name), code_of(home_name)
        if not away or not home or away == home:
            raise ValueError("UNKNOWN_OR_DUPLICATE_TEAM")
        at = datetime.strptime(f"{active_day.isoformat()} {hhmm}",
                               "%Y-%m-%d %H:%M").replace(tzinfo=TSI)
        key = (active_day.isoformat(), away, home)
        if key in seen:
            raise ValueError("DUPLICATE_FIXTURE")
        seen.add(key)
        delta = float(delta_text) if delta_text is not None else None
        if market_flag == "M+" and delta is None:
            # Equality can legitimately yield no delta label, but without
            # independent price evidence this still does not mean live odds.
            delta = 0.0
        if market_flag == "M-" and delta is not None:
            raise ValueError("UNMATCHED_FIXTURE_WITH_MOVI_CLOCK")
        result.append({
            "date_tsi": active_day.isoformat(),
            "start_tsi": at.strftime("%d.%m.%Y %H:%M"),
            "utc": at.astimezone(ZoneInfo("UTC")).isoformat(),
            "away": away_name, "home": home_name,
            "away_code": away, "home_code": home,
            "moviodds_saved_catalog": "PRESENT" if market_flag == "M+" else "NOT_LISTED",
            "moviodds_kickoff_delta_minutes": delta,
            "live_market_price_status": "NOT_VERIFIED",
        })
    result.sort(key=lambda x: (x["utc"], x["away_code"], x["home_code"]))
    found_yes = sum(row["moviodds_saved_catalog"] == "PRESENT" for row in result)
    found_no = len(result) - found_yes
    if (len(result), found_yes, found_no) != (expected_games, expected_yes, expected_no):
        raise ValueError("INCOMPLETE_WEEK_REPORT")
    for day, expected in day_counts.items():
        if sum(row["date_tsi"] == day.isoformat() for row in result) != expected:
            raise ValueError("INCOMPLETE_DAY_REPORT")
    if sum(day_counts.values()) != expected_games:
        raise ValueError("INCOMPLETE_DAY_HEADERS")
    return {
        "status": "OK",
        "kind": "SAVED_SNAPSHOT_NOT_LIVE_DATA",
        "provenance": "USER_SAVED_MOVIODDS_VS_ESPN_WEEK_AUDIT",
        "period_tsi": [first.isoformat(), last.isoformat()],
        "timezone": "Europe/Istanbul",
        "source_clock_is": "ESPN_COMPARISON_AT_PRIOR_RUN",
        "games": result,
        "count": len(result),
        "moviodds_saved_catalog_matched": found_yes,
        "moviodds_saved_catalog_missing": found_no,
        "network_calls": 0,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Convert saved NBA report into an OFFLINE JSON snapshot")
    ap.add_argument("--input", default="nba_week_21_27_full.txt")
    ap.add_argument("--output", default="nba_week_21_27_snapshot.json")
    opts = ap.parse_args()
    infile, outfile = Path(opts.input), Path(opts.output)
    if not infile.is_file() or infile.stat().st_size > 2_000_000:
        print(json.dumps({"status": "INPUT_MISSING_OR_LARGE", "network_calls": 0}))
        return
    try:
        data = import_saved_report(infile.read_text(encoding="utf-8"))
        outfile.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=".nba-week-", suffix=".json",
                                    dir=str(outfile.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                json.dump(data, out, ensure_ascii=False, indent=2)
                out.write("\n")
            os.replace(temp, outfile)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        print(json.dumps({"status": "SAVED_OFFLINE", "count": data["count"],
                          "week": data["period_tsi"], "network_calls": 0,
                          "output": str(outfile)}, ensure_ascii=False))
    except (OSError, UnicodeError, TypeError, ValueError):
        print(json.dumps({"status": "IMPORT_FAILED", "network_calls": 0}))


if __name__ == "__main__":
    main()
