"""Isolated MoviOdds basketball bulk-market probe (NOT wired to production).

Network is disabled unless --live and ZEYNAL_MOVIODDS_ENABLED=1 and
ZEYNAL_MOVIODDS_KEY is present. No model, archives, or settlement writes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import gzip
import io
import json
import math
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

URL = "https://moviodds.com/odds?sport=basketball"
MAX_COMPRESSED = 12 * 1024 * 1024
MAX_JSON = 25 * 1024 * 1024
FRESH_MINUTES = 30
ALIASES = {
    "nba": "NBA",
    "nationalbasketballassociation": "NBA",
    "euroleague": "EUROLEAGUE",
    "turkishairlineseuroleague": "EUROLEAGUE",
    "eurocup": "EUROCUP",
    "bkteurocup": "EUROCUP",
    "7dayseurocup": "EUROCUP",
}


def league_id(name: str) -> str | None:
    if not isinstance(name, str):
        return None
    return ALIASES.get(re.sub(r"[^a-z0-9]", "", name.lower()))


def utc_time(value: str) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result.astimezone(timezone.utc) if result.tzinfo else None


def inspect_board(board: dict, now: datetime | None = None) -> dict:
    """Count verified prematch evidence; do not invent line labels or odds."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not isinstance(board, dict) or not isinstance(board.get("matches"), list):
        return {"status": "BAD_SCHEMA", "leagues": {}, "covered": [], "unclassified": []}
    results = {"status": "WARMING" if board.get("warming") is True else "OK",
               "provider_market_scope": "main" if board.get("markets") == "main" else "not_declared",
               "leagues": {
        name: {"fixtures": 0, "listed_all_dates": 0, "priced": 0,
               "quoted_rows_seen": 0, "truncated_rows": 0,
               "fresh_quotes": 0, "stale_quotes": 0,
               "fixture_only_quotes": 0, "unknown_time_quotes": 0,
               "market_groups": []}
        for name in ("NBA", "EUROLEAGUE", "EUROCUP")
    }, "covered": [], "unclassified": []}
    server = utc_time(board.get("server_time")) or now
    # A server timestamp cannot be taken as a fresh quote timestamp.
    # Use per-market group_status first; a fixture polled_at proves only
    # that *some* groups were rechecked, not which ones.
    seen = set()
    groups = {league: set() for league in results["leagues"]}
    for match in board["matches"][:3000]:
        if not isinstance(match, dict):
            continue
        league = league_id(match.get("league"))
        if league is None:
            name = match.get("league")
            if isinstance(name, str) and "euro" in name.lower() and name not in results["unclassified"]:
                results["unclassified"].append(name[:80])
            continue
        results["leagues"][league]["listed_all_dates"] += 1
        kickoff = utc_time(match.get("kickoff_utc"))
        fixture_id = match.get("id")
        if not isinstance(fixture_id, (str, int)) or not str(fixture_id).strip() or kickoff is None:
            continue
        if (league, str(fixture_id)) in seen or not now < kickoff <= now + timedelta(hours=36):
            continue
        if match.get("in_play") is not False or not all(
            isinstance(match.get(key), str) and match[key].strip()
            for key in ("home", "away")
        ):
            continue
        seen.add((league, str(fixture_id)))
        current = results["leagues"][league]
        current["fixtures"] += 1
        quotes_seen = set()
        quotes = match.get("quotes")
        if not isinstance(quotes, list):
            continue
        current["quoted_rows_seen"] += len(quotes)
        current["truncated_rows"] += max(0, len(quotes) - 10000)
        group_status = match.get("group_status")
        if not isinstance(group_status, dict):
            group_status = {}
        fixture_polled = utc_time(match.get("polled_at"))
        for quote in quotes[:10000]:
            if not isinstance(quote, dict) or quote.get("suspended") is True:
                continue
            price = quote.get("odds_dec")
            if type(price) not in (float, int) or not math.isfinite(price) or not (1 < price <= 1000):
                continue
            sel_id = quote.get("sel_id")
            if not sel_id:
                continue
            # Same group_id can contain several market_id values.
            # sel_id/market_id alone are not sufficient for deduplication.
            group_id = str(quote.get("group_id") or "")
            identity = (group_id, str(quote.get("market_id") or ""),
                        str(quote.get("market_key") or ""), str(sel_id))
            if identity in quotes_seen:
                continue
            quotes_seen.add(identity)
            group = quote.get("group_name") or quote.get("group_id")
            if isinstance(group, (str, int)):
                groups[league].add(str(group)[:80])
            group_record = group_status.get(group_id)
            if not isinstance(group_record, dict):
                group_record = {}
            group_polled = utc_time(group_record.get("polled_at"))
            if group_record.get("stale") is True:
                current["stale_quotes"] += 1
            elif group_polled is not None:
                age = server - group_polled
                if -timedelta(minutes=1) <= age <= timedelta(minutes=FRESH_MINUTES):
                    current["fresh_quotes"] += 1
                else:
                    current["stale_quotes"] += 1
            elif fixture_polled is not None:
                # Never treat a recheck of a different group as proof
                # that *this* market's prices are confirmed.
                current["fixture_only_quotes"] += 1
            else:
                # Even if price-change ts exists, it says nothing about liveness.
                current["unknown_time_quotes"] += 1
        if quotes_seen:
            current["priced"] += 1
    results["covered"] = [lg for lg, row in results["leagues"].items() if row["fixtures"]]
    for league in groups:
        results["leagues"][league]["market_groups"] = sorted(groups[league])[:80]
    return results


def classify_http_error(exc: HTTPError, key: str) -> str:
    """Categorize a provider error without printing provider text or credentials."""
    if exc.code == 401:
        return "KEY_MISSING_OR_INVALID"
    if exc.code == 403:
        return "ACCESS_NOT_ALLOWED"
    if exc.code == 429:
        return "RATE_LIMIT"
    if exc.code == 503:
        return "PROVIDER_BUSY"
    if exc.code != 400:
        return "HTTP_UNCLASSIFIED"
    try:
        raw = exc.read(4096)
        payload = json.loads(raw)
        error = payload.get("error", "")
        if not isinstance(error, str):
            return "BAD_REQUEST_UNCLASSIFIED"
        normalized = error.lower()
        if "unknown sport" in normalized:
            return "UNKNOWN_SPORT_FILTER"
        if "invalid or revoked api key" in normalized or "api key required" in normalized:
            return "KEY_MISSING_OR_INVALID"
        if "invalid" in normalized and "parameter" in normalized:
            return "INVALID_PARAMETER"
        if "unknown" in normalized and ("site" in normalized or "filter" in normalized):
            return "UNSUPPORTED_FILTER"
        return "BAD_REQUEST_UNCLASSIFIED"
    except (OSError, UnicodeDecodeError, ValueError, TypeError, AttributeError):
        return "BAD_REQUEST_UNCLASSIFIED"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_live_board(key: str) -> dict:
    """One fixed-host read, max response size, TLS verification by urllib defaults."""
    req = Request(URL, headers={
        "X-API-Key": key,
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "User-Agent": "ZEYNAL-TestOnly-MarketProbe/1",
    })
    with build_opener(NoRedirect()).open(req, timeout=20) as response:
        if response.status != 200 or response.headers.get_content_type() != "application/json":
            raise ValueError("UNEXPECTED_HTTP_RESPONSE")
        body = response.read(MAX_COMPRESSED + 1)
        if len(body) > MAX_COMPRESSED:
            raise ValueError("RESPONSE_TOO_LARGE")
        if response.headers.get("Content-Encoding", "").lower() == "gzip":
            with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
                body = stream.read(MAX_JSON + 1)
        if len(body) > MAX_JSON:
            raise ValueError("JSON_TOO_LARGE")
        return json.loads(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="MoviOdds test-only bulk-market probe")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not args.live:
        result = {"status": "OFFLINE_ONLY", "endpoint": URL, "network_calls": 0}
    elif os.getenv("ZEYNAL_MOVIODDS_ENABLED") != "1" or not os.getenv("ZEYNAL_MOVIODDS_KEY"):
        result = {"status": "NOT_AUTHORIZED", "network_calls": 0}
    else:
        try:
            result = inspect_board(read_live_board(os.environ["ZEYNAL_MOVIODDS_KEY"]))
            result["network_calls"] = 1
        except HTTPError as exc:
            code = exc.code
            category = classify_http_error(exc, os.environ["ZEYNAL_MOVIODDS_KEY"])
            exc.close()
            result = {"status": "HTTP_ERROR", "http_status": code,
                      "error_category": category, "network_calls": 1}
        except (URLError, OSError, ValueError, json.JSONDecodeError):
            result = {"status": "SOURCE_UNAVAILABLE", "network_calls": 1}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
