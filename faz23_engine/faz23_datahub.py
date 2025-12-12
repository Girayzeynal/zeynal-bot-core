# -*- coding: utf-8 -*-
"""
FAZ-23 DataHub (FINAL BUILD)

Amaç:
- Dış API'lerden maç bağlamı + total bazlı özet topla
- Bu modül ASLA exception fırlatmaz (hata olursa loglar, used=False döner)
- Tek giriş: fetch_match_totals(league, date_str, home, away)

ENV:
- API_BASK_KEY   : API-SPORTS key (basketball)
- ODDS_API_KEY   : Odds API key

Opsiyonel ENV:
- API_BASK_BASE_URL : default "https://v1.basketball.api-sports.io"
- ODDS_BASE_URL     : default "https://api.the-odds-api.com/v4"
- ODDS_SPORT_KEY_NBA: default "basketball_nba"
- HTTP_TIMEOUT_CONNECT: default "3.0"
- HTTP_TIMEOUT_READ   : default "8.0"
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional, Tuple

import requests

from faz23_engine.faz23_team_map import map_team

from faz23_engine import faz23_team_map
faz23_team_map._faz23_team_map_runtime_anchor()

log = logging.getLogger("faz23-datahub")


def _timeouts() -> Tuple[float, float]:
    try:
        c = float(os.getenv("HTTP_TIMEOUT_CONNECT", "3.0"))
        r = float(os.getenv("HTTP_TIMEOUT_READ", "8.0"))
        return c, r
    except Exception:
        return 3.0, 8.0


@dataclass
class ApiSportsSample:
    provider: str = "API-SPORTS"
    league_total_baseline: Optional[float] = None
    team_total_baseline: Optional[float] = None
    raw: Optional[Dict[str, Any]] = None


@dataclass
class OddsSample:
    provider: str = "ODDS_API"
    market_total: Optional[float] = None
    bookmaker: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


def _detect_family(league: str) -> str:
    s = (league or "").strip().upper()
    if "NBA" in s:
        return "NBA"
    if "EURO" in s:
        return "EUROLEAGUE"
    return s or "UNKNOWN"


def _safe_get_json(url: str, headers: Dict[str, str], params: Dict[str, Any]) -> Dict[str, Any]:
    """
    requests.get -> json, her türlü hatada {} döndürür.
    """
    try:
        c_to, r_to = _timeouts()
        resp = requests.get(url, headers=headers, params=params, timeout=(c_to, r_to))
        status = resp.status_code
        if status < 200 or status >= 300:
            log.warning("HTTP %s for %s | params=%s | body=%s", status, url, params, resp.text[:400])
            return {}
        try:
            return resp.json() or {}
        except Exception:
            log.warning("JSON parse fail for %s | body=%s", url, resp.text[:400])
            return {}
    except Exception as e:
        log.warning("HTTP request fail: %s | url=%s | params=%s", e, url, params)
        return {}


def _fetch_api_sports_totals(date_str: str, home: str, away: str) -> Dict[str, Any]:
    """
    API-SPORTS Basketball:
    - En güvenlisi: günün maçlarını çek -> home/away eşleştir -> totals benzeri sinyal çıkar.
    Not: API-SPORTS planına göre endpoint detayları değişebilir; burada "best-effort" yapıyoruz.
    """
    key = (os.getenv("API_BASK_KEY") or "").strip()
    if not key:
        return {"used": False, "error": "API_BASK_KEY missing"}

    base = (os.getenv("API_BASK_BASE_URL") or "https://v1.basketball.api-sports.io").rstrip("/")
    url = f"{base}/games"

    # API-SPORTS genelde bu header ile çalışır:
    headers = {"x-apisports-key": key}

    home_c = map_team(home)
    away_c = map_team(away)

    data = _safe_get_json(url, headers=headers, params={"date": date_str})
    if not data:
        return {"used": False, "error": "empty response", "raw": None}

    resp_list = data.get("response") or []
    if not isinstance(resp_list, list) or not resp_list:
        return {"used": False, "error": "no games in response", "raw": data}

    # Maçı bul
    found = None
    for g in resp_list:
        try:
            teams = g.get("teams") or {}
            h = teams.get("home", {}).get("name", "")
            a = teams.get("away", {}).get("name", "")
            if map_team(h) == home_c and map_team(a) == away_c:
                found = g
                break
        except Exception:
            continue

    if not found:
        # bazen ev/deplasman ters gelir; onu da dene
        for g in resp_list:
            try:
                teams = g.get("teams") or {}
                h = teams.get("home", {}).get("name", "")
                a = teams.get("away", {}).get("name", "")
                if map_team(h) == away_c and map_team(a) == home_c:
                    found = g
                    break
            except Exception:
                continue

    if not found:
        return {"used": False, "error": "match not found", "raw": {"date": date_str, "home": home_c, "away": away_c}}

    # API-SPORTS bazen "scores" / "status" verir; total baseline için farklı alanlar olabilir.
    # Burada: eğer bir "scores" datası varsa toplayıp live_total gibi döndürüyoruz.
    live_total = None
    try:
        scores = found.get("scores") or {}
        hpts = scores.get("home", {}).get("total")
        apts = scores.get("away", {}).get("total")
        if isinstance(hpts, (int, float)) and isinstance(apts, (int, float)):
            live_total = float(hpts + apts)
    except Exception:
        live_total = None

    sample = ApiSportsSample(
        league_total_baseline=None,
        team_total_baseline=None,
        raw={"match": found, "live_total": live_total},
    )

    return {"used": True, **asdict(sample)}


def _fetch_odds_api_total(date_str: str, home: str, away: str, family: str) -> Dict[str, Any]:
    """
    Odds API:
    - Total market çizgisini çekmeye çalışır.
    - NBA için ODDS_SPORT_KEY_NBA env ile sport key ayarlanabilir.
    """
    key = (os.getenv("ODDS_API_KEY") or "").strip()
    if not key:
        return {"used": False, "error": "ODDS_API_KEY missing"}

    base = (os.getenv("ODDS_BASE_URL") or "https://api.the-odds-api.com/v4").rstrip("/")
    sport_key = os.getenv("ODDS_SPORT_KEY_NBA", "basketball_nba") if family == "NBA" else None
    if not sport_key:
        return {"used": False, "error": f"no ODDS sport key for family={family}"}

    # Odds API v4 örnek endpoint mantığı:
    # /sports/{sport_key}/odds/?regions=us&markets=totals&oddsFormat=decimal&apiKey=...
    url = f"{base}/sports/{sport_key}/odds"

    params = {
        "regions": "us",
        "markets": "totals",
        "oddsFormat": "decimal",
        "dateFormat": "iso",
        "apiKey": key,
    }

    data = _safe_get_json(url, headers={}, params=params)
    if not isinstance(data, list) or not data:
        # Odds API burada genelde list döner; boşsa hata yok ama veri yok
        return {"used": False, "error": "empty odds list", "raw": data}

    home_c = map_team(home)
    away_c = map_team(away)

    # maç eşle
    matched = None
    for ev in data:
        try:
            h = ev.get("home_team", "")
            a = ev.get("away_team", "")
            if map_team(h) == home_c and map_team(a) == away_c:
                matched = ev
                break
        except Exception:
            continue

    if not matched:
        return {"used": False, "error": "odds match not found", "raw": {"date": date_str, "home": home_c, "away": away_c}}

    # totals line seç
    market_total = None
    bookmaker_name = None
    try:
        books = matched.get("bookmakers") or []
        for b in books:
            mks = b.get("markets") or []
            for mk in mks:
                if mk.get("key") == "totals":
                    outcomes = mk.get("outcomes") or []
                    # outcomes içinde genelde "Over" ve "Under" aynı point değerinde olur
                    points = []
                    for o in outcomes:
                        p = o.get("point")
                        if isinstance(p, (int, float)):
                            points.append(float(p))
                    if points:
                        market_total = round(sum(points) / len(points), 1)
                        bookmaker_name = b.get("title") or b.get("key")
                        raise StopIteration  # çık
    except StopIteration:
        pass
    except Exception:
        market_total = None

    sample = OddsSample(
        market_total=market_total,
        bookmaker=bookmaker_name,
        raw={"event": matched},
    )

    used = market_total is not None
    return {"used": used, **asdict(sample)}


def fetch_match_totals(league: str, date_str: str, home: str, away: str) -> Dict[str, Any]:
    """
    FAZ-13 orchestrator tarafından çağrılan ana fonksiyon.
    DÖNÜŞ: asla exception fırlatmaz.
    """
    family = _detect_family(league)

    api_sports_block: Optional[Dict[str, Any]] = None
    odds_block: Optional[Dict[str, Any]] = None

    # API-SPORTS
    try:
        api_sports_block = _fetch_api_sports_totals(date_str=date_str, home=home, away=away)
    except Exception as e:
        log.warning("FAZ23 DataHub API-SPORTS exception: %s", e)
        api_sports_block = {"used": False, "error": str(e)}

    # ODDS
    try:
        odds_block = _fetch_odds_api_total(date_str=date_str, home=home, away=away, family=family)
    except Exception as e:
        log.warning("FAZ23 DataHub ODDS exception: %s", e)
        odds_block = {"used": False, "error": str(e)}

    # “has_odds” bayrağı
    has_odds = bool(odds_block and odds_block.get("used") and odds_block.get("market_total") is not None)

    out: Dict[str, Any] = {
        "family": family,
        "league": league,
        "date": date_str,
        "home": map_team(home),
        "away": map_team(away),
        "league_total_baseline": None,  # ileride doldurabilirsin
        "team_total_baseline": None,    # ileride doldurabilirsin
        "has_odds": has_odds,
        "odds": odds_block if odds_block else {"used": False},
        "api_sports": api_sports_block if api_sports_block else {"used": False},
    }
    return out
