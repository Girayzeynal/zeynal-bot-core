# -*- coding: utf-8 -*-
"""
FAZ-23 DataHub (FINAL BUILD)

Amaç:
- Dış API'lerden maç bağlamı + total bazlı özet topla
- Bu modül ASLA exception fırlatmaz (hata olursa loglar, used=False döner)
- Tek giriş: fetch_match_totals(league, date_str, home, away)

ENV:
- API_BASK_KEY              : API-SPORTS key (basketball)
- ODDS_API_KEY              : The Odds API key

Opsiyonel ENV:
- API_BASK_BASE_URL         : default "https://v1.basketball.api-sports.io"
- ODDS_BASE_URL             : default "https://api.the-odds-api.com/v4"
- ODDS_REGIONS              : default "us"
- ODDS_MARKETS              : default "totals"
- ODDS_DATE_FILTER          : default "0"  (1 => commenceTimeFrom/To ile tarihi daraltır)
- ODDS_SPORT_KEY_NBA        : default "basketball_nba"
- ODDS_SPORT_KEY_EUROLEAGUE : default ""   (BUNU SET ETMEN LAZIM)
- HTTP_TIMEOUT_CONNECT      : default "3.0"
- HTTP_TIMEOUT_READ         : default "8.0"
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional, Tuple, Union, List

import requests

# ✅ Kritik: paket import'u yerine doğrudan modül fonksiyonu import et
from faz23_engine.faz23_team_map import map_team

log = logging.getLogger("faz23-datahub")


def _timeouts() -> Tuple[float, float]:
    try:
        c = float(os.getenv("HTTP_TIMEOUT_CONNECT", "3.0"))
        r = float(os.getenv("HTTP_TIMEOUT_READ", "8.0"))
        return c, r
    except Exception:
        return 3.0, 8.0


def _safe_get_json(
    url: str,
    headers: Dict[str, str],
    params: Dict[str, Any],
) -> Union[Dict[str, Any], List[Any]]:
    """
    requests.get -> json
    Her türlü hatada {} ya da [] döndürür (çağıran taraf tip kontrolü yapar).
    """
    try:
        c_to, r_to = _timeouts()
        resp = requests.get(url, headers=headers, params=params, timeout=(c_to, r_to))
        if resp.status_code < 200 or resp.status_code >= 300:
            log.warning(
                "HTTP %s for %s | params=%s | body=%s",
                resp.status_code,
                url,
                params,
                resp.text[:400],
            )
            return {}

        try:
            data = resp.json()
            return data if data is not None else {}
        except Exception:
            log.warning("JSON parse fail for %s | body=%s", url, resp.text[:400])
            return {}
    except Exception as e:
        log.warning("HTTP request fail: %s | url=%s | params=%s", e, url, params)
        return {}


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


def _parse_utc_date_window(date_str: str) -> Tuple[str, str]:
    """
    date_str: YYYY-MM-DD  (UTC kabul ediyoruz)
    commenceTimeFrom/To için ISO string döndürür.
    """
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        # parse edemezsek "bugün" fallback (UTC)
        d = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    start = d
    end = d + timedelta(days=1)
    return start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")


def _fetch_api_sports_totals(date_str: str, home: str, away: str) -> Dict[str, Any]:
    """
    API-SPORTS Basketball:
    - Günün maçlarını çek -> home/away eşleştir -> totals sinyali (varsa live total)
    Not: Prematch totals sağlamıyorsa 'baseline' boş kalabilir. Ama en azından eşleşme doğrular.
    """
    key = (os.getenv("API_BASK_KEY") or "").strip()
    if not key:
        return {"used": False, "error": "API_BASK_KEY missing"}

    base = (os.getenv("API_BASK_BASE_URL") or "https://v1.basketball.api-sports.io").rstrip("/")
    url = f"{base}/games"
    headers = {"x-apisports-key": key}

    home_c = map_team(home)
    away_c = map_team(away)

    data = _safe_get_json(url, headers=headers, params={"date": date_str})
    if not isinstance(data, dict) or not data:
        return {"used": False, "error": "empty response", "raw": None}

    resp_list = data.get("response") or []
    if not isinstance(resp_list, list) or not resp_list:
        return {"used": False, "error": "no games in response", "raw": data}

    found: Optional[Dict[str, Any]] = None

    # 1) normal eşleşme
    for g in resp_list:
        try:
            teams = g.get("teams") or {}
            h = (teams.get("home") or {}).get("name", "")
            a = (teams.get("away") or {}).get("name", "")
            if map_team(h) == home_c and map_team(a) == away_c:
                found = g
                break
        except Exception:
            continue

    # 2) ters eşleşme
    if not found:
        for g in resp_list:
            try:
                teams = g.get("teams") or {}
                h = (teams.get("home") or {}).get("name", "")
                a = (teams.get("away") or {}).get("name", "")
                if map_team(h) == away_c and map_team(a) == home_c:
                    found = g
                    break
            except Exception:
                continue

    if not found:
        return {
            "used": False,
            "error": "match not found",
            "raw": {"date": date_str, "home": home_c, "away": away_c},
        }

    live_total: Optional[float] = None
    try:
        scores = found.get("scores") or {}
        hpts = (scores.get("home") or {}).get("total")
        apts = (scores.get("away") or {}).get("total")
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


def _odds_sport_key_for_family(family: str) -> str:
    if family == "NBA":
        return os.getenv("ODDS_SPORT_KEY_NBA", "basketball_nba").strip()
    if family == "EUROLEAGUE":
        return (os.getenv("ODDS_SPORT_KEY_EUROLEAGUE") or "").strip()
    return ""


def _fetch_odds_api_total(date_str: str, home: str, away: str, family: str) -> Dict[str, Any]:
    """
    The Odds API:
    - Total market çizgisini çekmeye çalışır.
    - Sport key family'e göre seçilir.
    - ODDS_DATE_FILTER=1 ise UTC gün penceresi ile filtreler.
    """
    key = (os.getenv("ODDS_API_KEY") or "").strip()
    if not key:
        return {"used": False, "error": "ODDS_API_KEY missing"}

    base = (os.getenv("ODDS_BASE_URL") or "https://api.the-odds-api.com/v4").rstrip("/")
    sport_key = _odds_sport_key_for_family(family)
    if not sport_key:
        return {"used": False, "error": f"no ODDS sport key for family={family}"}

    url = f"{base}/sports/{sport_key}/odds"

    regions = (os.getenv("ODDS_REGIONS") or "us").strip()
    markets = (os.getenv("ODDS_MARKETS") or "totals").strip()

    params: Dict[str, Any] = {
        "regions": regions,
        "markets": markets,
        "oddsFormat": "decimal",
        "dateFormat": "iso",
        "apiKey": key,
    }

    if (os.getenv("ODDS_DATE_FILTER") or "0").strip() == "1":
        c_from, c_to = _parse_utc_date_window(date_str)
        params["commenceTimeFrom"] = c_from
        params["commenceTimeTo"] = c_to

    data = _safe_get_json(url, headers={}, params=params)
    if not isinstance(data, list) or not data:
        return {"used": False, "error": "empty odds list", "raw": data}

    home_c = map_team(home)
    away_c = map_team(away)

    matched: Optional[Dict[str, Any]] = None
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
        return {
            "used": False,
            "error": "odds match not found",
            "raw": {"date": date_str, "home": home_c, "away": away_c},
        }

    market_total: Optional[float] = None
    bookmaker_name: Optional[str] = None

    try:
        books = matched.get("bookmakers") or []
        for b in books:
            mks = b.get("markets") or []
            for mk in mks:
                if mk.get("key") != "totals":
                    continue
                outcomes = mk.get("outcomes") or []
                points: List[float] = []
                for o in outcomes:
                    p = o.get("point")
                    if isinstance(p, (int, float)):
                        points.append(float(p))
                if points:
                    market_total = round(sum(points) / len(points), 1)
                    bookmaker_name = b.get("title") or b.get("key")
                    raise StopIteration
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

    # ================================
    # FAZ-23 DATAHUB DEBUG (STEP-1)
    # ================================
    try:
        log.warning(
            "[FAZ23-DATAHUB-DEBUG] api_sports.used=%s odds.used=%s "
            "league_total=%s team_total=%s market_total=%s",
            bool(api_sports_block and api_sports_block.get("used")),
            bool(odds_block and odds_block.get("used")),
            api_sports_block.get("league_total_baseline") if api_sports_block else None,
            api_sports_block.get("team_total_baseline") if api_sports_block else None,
            odds_block.get("market_total") if odds_block else None,
        )
    except Exception as _e:
        log.warning("[FAZ23-DATAHUB-DEBUG] failed: %s", _e)

    has_odds = bool(
        odds_block
        and odds_block.get("used")
        and odds_block.get("market_total") is not None
    )

    out: Dict[str, Any] = {
        "family": family,
        "league": league,
        "date": date_str,
        "home": map_team(home),
        "away": map_team(away),
        "league_total_baseline": None,
        "team_total_baseline": None,
        "has_odds": has_odds,
        "odds": odds_block if odds_block else {"used": False},
        "api_sports": api_sports_block if api_sports_block else {"used": False},
    }
    return out


__all__ = ["fetch_match_totals"]
