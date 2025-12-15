# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import json
import time
import urllib.request
import urllib.parse
from typing import Any, Dict, Optional, Tuple


def _now() -> int:
    return int(time.time())


def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _http_get_json(url: str, headers: Dict[str, str], timeout: int = 10) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    try:
        return json.loads(raw)
    except Exception:
        return {"_raw": raw}


def odds_api_fetch_market(
    *,
    league: str,
    date_str: str,
    home: str,
    away: str,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    ODDS API provider (minimal, totals line odaklı).

    Çıktı market_data örneği:
    {
      "provider": "odds_api",
      "totals_line": 229.5,
      "over_odds": 1.90,
      "under_odds": 1.90,
      "book": "...",
      "raw": {...optional...}
    }
    """
    api_key = (os.getenv("ODDS_API_KEY", "") or "").strip()
    if not api_key:
        return None, {"used": False, "reason": "ODDS_API_KEY_missing", "provider": "odds_api", "ts": _now()}

    # Odds API endpoint’leri değişebiliyor; bu yüzden “safe parse” + raw saklıyoruz.
    # Burada amaç: totals line + over/under odds yakalamak.
    #
    # Not: League mapping'i senin elite registry tarafında da olabilir;
    # burada minimal tutuyoruz.
    sport = "basketball_nba" if league.upper() == "NBA" else "basketball"
    regions = "us"
    markets = "totals"
    odds_format = "decimal"
    date_format = "iso"

    qs = urllib.parse.urlencode({
        "apiKey": api_key,
        "regions": regions,
        "markets": markets,
        "oddsFormat": odds_format,
        "dateFormat": date_format,
    })

    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?{qs}"
    headers = {"Accept": "application/json"}

    try:
        data = _http_get_json(url, headers=headers, timeout=12)
    except Exception as e:
        return None, {"used": False, "reason": f"http_exception:{e}", "provider": "odds_api", "ts": _now()}

    if not isinstance(data, list):
        return None, {"used": False, "reason": "bad_response_type", "provider": "odds_api", "ts": _now(), "raw": data}

    # Maçı bul: home/away isim eşleşmesi gevşek
    h = (home or "").lower().strip()
    a = (away or "").lower().strip()

    def _norm_team(s: str) -> str:
        return (s or "").lower().strip()

    picked = None
    for item in data:
        try:
            home_team = _norm_team(item.get("home_team", ""))
            away_team = _norm_team(item.get("away_team", ""))
            # bazı kaynaklar home/away ters basabiliyor; iki yön de kontrol
            if (home_team == h and away_team == a) or (home_team == a and away_team == h):
                picked = item
                break
        except Exception:
            continue

    if not picked:
        return None, {"used": False, "reason": "match_not_found", "provider": "odds_api", "ts": _now()}

    # Totals market parse
    totals_line = None
    over_odds = None
    under_odds = None
    book_name = None

    books = picked.get("bookmakers") or []
    for b in books:
        try:
            book_name = b.get("title") or book_name
            markets_arr = b.get("markets") or []
            for m in markets_arr:
                if (m.get("key") or "").lower() != "totals":
                    continue
                outcomes = m.get("outcomes") or []
                for o in outcomes:
                    name = (o.get("name") or "").lower()
                    point = _safe_float(o.get("point"))
                    price = _safe_float(o.get("price"))
                    if point is not None and totals_line is None:
                        totals_line = point
                    if "over" in name:
                        over_odds = price
                    if "under" in name:
                        under_odds = price
            if totals_line is not None:
                break
        except Exception:
            continue
        if totals_line is not None:
            break

    if totals_line is None:
        return None, {"used": False, "reason": "totals_line_not_found", "provider": "odds_api", "ts": _now(), "raw": picked}

    market_data = {
        "provider": "odds_api",
        "totals_line": float(totals_line),
        "over_odds": over_odds,
        "under_odds": under_odds,
        "book": book_name,
        # İstersen debug için aç:
        # "raw": picked,
    }
    return market_data, {"used": True, "reason": "ok", "provider": "odds_api", "ts": _now()}
