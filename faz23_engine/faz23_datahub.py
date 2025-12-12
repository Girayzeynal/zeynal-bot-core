# -*- coding: utf-8 -*-
"""
FAZ-23 DataHub (FINAL BUILD v2)

Amaç:
- Dış API'lerden maç bağlamı + total bazlı özet topla
- Bu modül ASLA exception fırlatmaz (hata olursa loglar, used=False döner)
- Tek giriş: fetch_match_totals(league, date_str, home, away)

ENV:
- API_BASK_KEY     : API-SPORTS key (basketball)
- ODDS_API_KEY     : Odds API key

Opsiyonel ENV:
- API_BASK_BASE_URL          : default "https://v1.basketball.api-sports.io"
- ODDS_BASE_URL              : default "https://api.the-odds-api.com/v4"
- ODDS_REGIONS               : default "us,eu"     (virgüllü)
- ODDS_MARKETS               : default "totals"    (virgüllü, ama biz totals kullanıyoruz)
- ODDS_SPORT_KEY_NBA         : default "basketball_nba"
- ODDS_SPORT_KEY_EUROLEAGUE  : default ""  (BUNU SET ETMEN LAZIM)
- ODDS_DATE_FILTER           : default "1"  (1=aktif) -> commenceTimeFrom/To ile tarihi daraltır
- HTTP_TIMEOUT_CONNECT       : default "3.0"
- HTTP_TIMEOUT_READ          : default "8.0"

ÇIKTI:
{
  "family": "...",
  "league": "...",
  "date": "YYYY-MM-DD",
  "home": "...",
  "away": "...",
  "league_total_baseline": None,
  "team_total_baseline": None,
  "has_odds": bool,
  "odds": {...},
  "api_sports": {...}
}
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional, Tuple, List
from datetime import datetime, timezone, timedelta

import requests

# ✅ Kritik: paket import'u yerine direkt modül fonksiyonu
from faz23_engine.faz23_team_map import map_team

log = logging.getLogger("faz23-datahub")


# ================================================================
# ✅ Runtime anchor (deploy/import sırasında patlamasın)
# ================================================================
def _safe_team_map_anchor() -> None:
    try:
        import faz23_engine.faz23_team_map as _tm  # noqa: F401
        anchor = getattr(_tm, "_faz23_team_map_runtime_anchor", None)
        if callable(anchor):
            anchor()
    except Exception as e:
        log.debug("FAZ23 team_map anchor skipped: %s", e)


_safe_team_map_anchor()


# ================================================================
# Helpers
# ================================================================
def _timeouts() -> Tuple[float, float]:
    try:
        c = float(os.getenv("HTTP_TIMEOUT_CONNECT", "3.0"))
        r = float(os.getenv("HTTP_TIMEOUT_READ", "8.0"))
        return c, r
    except Exception:
        return 3.0, 8.0


def _truthy_env(key: str, default: str = "0") -> bool:
    v = (os.getenv(key, default) or "").strip().lower()
    return v in ("1", "true", "yes", "on", "y", "ok")


def _safe_get_json(url: str, headers: Dict[str, str], params: Dict[str, Any]) -> Any:
    """requests.get -> json, her türlü hatada {} veya [] döndürür (duruma göre)."""
    try:
        c_to, r_to = _timeouts()
        resp = requests.get(url, headers=headers, params=params, timeout=(c_to, r_to))
        status = resp.status_code
        if status < 200 or status >= 300:
            log.warning("HTTP %s for %s | params=%s | body=%s", status, url, params, resp.text[:400])
            return {}
        try:
            return resp.json()
        except Exception:
            log.warning("JSON parse fail for %s | body=%s", url, resp.text[:400])
            return {}
    except Exception as e:
        log.warning("HTTP request fail: %s | url=%s | params=%s", e, url, params)
        return {}


def _detect_family(league: str) -> str:
    s = (league or "").strip().upper()
    if "NBA" in s:
        return "NBA"
    if "EURO" in s:
        return "EUROLEAGUE"
    return s or "UNKNOWN"


def _iso_window_for_date_utc(date_str: str) -> Tuple[str, str]:
    """
    OddsAPI 'commenceTimeFrom/To' ISO istiyor.
    date_str = YYYY-MM-DD (UTC kabul edeceğiz)
    """
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        start = d
        end = d + timedelta(days=1) - timedelta(seconds=1)
        # OddsAPI genelde Z sever
        return start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")
    except Exception:
        # Fallback: filtreleme yok
        return "", ""


def _norm_team(s: str) -> str:
    return map_team(s or "").strip().upper()


def _teams_match(home_a: str, away_a: str, home_b: str, away_b: str) -> bool:
    return _norm_team(home_a) == _norm_team(home_b) and _norm_team(away_a) == _norm_team(away_b)


def _teams_match_swapped(home_a: str, away_a: str, home_b: str, away_b: str) -> bool:
    return _norm_team(home_a) == _norm_team(away_b) and _norm_team(away_a) == _norm_team(home_b)


def _resolve_odds_sport_key(family: str) -> Optional[str]:
    """
    NBA için default var.
    Euroleague için kesin env set etmen lazım.
    """
    if family == "NBA":
        return (os.getenv("ODDS_SPORT_KEY_NBA", "basketball_nba") or "").strip() or None
    if family == "EUROLEAGUE":
        # Bunu sen set edeceksin. OddsAPI'de tam adı değişebiliyor.
        return (os.getenv("ODDS_SPORT_KEY_EUROLEAGUE", "") or "").strip() or None
    return None


# ================================================================
# Data blocks
# ================================================================
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


# ================================================================
# Provider: API-SPORTS
# ================================================================
def _fetch_api_sports_totals(date_str: str, home: str, away: str) -> Dict[str, Any]:
    """
    API-SPORTS Basketball:
    - Günün maçlarını çek -> home/away eşleştir
    - "scores.total" yakalarsa live_total döndürür (prematchte None normal)
    """
    key = (os.getenv("API_BASK_KEY") or "").strip()
    if not key:
        return {"used": False, "error": "API_BASK_KEY missing"}

    base = (os.getenv("API_BASK_BASE_URL") or "https://v1.basketball.api-sports.io").rstrip("/")
    url = f"{base}/games"
    headers = {"x-apisports-key": key}

    home_c = _norm_team(home)
    away_c = _norm_team(away)

    data = _safe_get_json(url, headers=headers, params={"date": date_str})
    if not data:
        return {"used": False, "error": "empty response", "raw": None}

    resp_list = data.get("response") or []
    if not isinstance(resp_list, list) or not resp_list:
        return {"used": False, "error": "no games in response", "raw": data}

    found = None
    for g in resp_list:
        try:
            teams = g.get("teams") or {}
            h = (teams.get("home") or {}).get("name", "")
            a = (teams.get("away") or {}).get("name", "")
            if _teams_match(h, a, home_c, away_c):
                found = g
                break
        except Exception:
            continue

    if not found:
        for g in resp_list:
            try:
                teams = g.get("teams") or {}
                h = (teams.get("home") or {}).get("name", "")
                a = (teams.get("away") or {}).get("name", "")
                if _teams_match_swapped(h, a, home_c, away_c):
                    found = g
                    break
            except Exception:
                continue

    if not found:
        return {"used": False, "error": "match not found", "raw": {"date": date_str, "home": home_c, "away": away_c}}

    live_total = None
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


# ================================================================
# Provider: ODDS API
# ================================================================
def _extract_market_total_from_event(ev: Dict[str, Any]) -> Tuple[Optional[float], Optional[str]]:
    """
    Ev içinden totals marketini yakala.
    Bazı booklarda outcomes 2 adet olur (Over/Under), ikisinin point'i aynı olur.
    Yine de ortalama alıyoruz.
    """
    market_total = None
    bookmaker_name = None

    try:
        books = ev.get("bookmakers") or []
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
                    return market_total, bookmaker_name
    except Exception:
        return None, None

    return None, None


def _fetch_odds_api_total(date_str: str, home: str, away: str, family: str) -> Dict[str, Any]:
    """
    Odds API:
    - sport_key family bazlı (NBA default var, Euroleague env şart)
    - date filtre: commenceTimeFrom/To ile o günü daraltır
    - eşleşme: home/away ve swapped kontrol
    """
    key = (os.getenv("ODDS_API_KEY") or "").strip()
    if not key:
        return {"used": False, "error": "ODDS_API_KEY missing"}

    sport_key = _resolve_odds_sport_key(family)
    if not sport_key:
        return {"used": False, "error": f"no ODDS sport key for family={family} (set ODDS_SPORT_KEY_...)"}

    base = (os.getenv("ODDS_BASE_URL") or "https://api.the-odds-api.com/v4").rstrip("/")
    url = f"{base}/sports/{sport_key}/odds"

    regions = (os.getenv("ODDS_REGIONS", "us,eu") or "us,eu").strip()
    params: Dict[str, Any] = {
        "regions": regions,
        "markets": "totals",
        "oddsFormat": "decimal",
        "dateFormat": "iso",
        "apiKey": key,
    }

    # ✅ Tarih filtresi (çok kritik)
    if _truthy_env("ODDS_DATE_FILTER", "1"):
        t_from, t_to = _iso_window_for_date_utc(date_str)
        if t_from and t_to:
            params["commenceTimeFrom"] = t_from
            params["commenceTimeTo"] = t_to

    data = _safe_get_json(url, headers={}, params=params)
    if not isinstance(data, list) or not data:
        return {"used": False, "error": "empty odds list", "raw": data}

    home_c = _norm_team(home)
    away_c = _norm_team(away)

    matched = None

    # 1) direkt match
    for ev in data:
        try:
            h = ev.get("home_team", "")
            a = ev.get("away_team", "")
            if _teams_match(h, a, home_c, away_c):
                matched = ev
                break
        except Exception:
            continue

    # 2) swapped match
    if not matched:
        for ev in data:
            try:
                h = ev.get("home_team", "")
                a = ev.get("away_team", "")
                if _teams_match_swapped(h, a, home_c, away_c):
                    matched = ev
                    break
            except Exception:
                continue

    if not matched:
        # Debug için biraz daha bilgi bırak
        return {
            "used": False,
            "error": "odds match not found",
            "raw": {
                "date": date_str,
                "home": home_c,
                "away": away_c,
                "sport_key": sport_key,
                "regions": regions,
                "count": len(data),
            },
        }

    market_total, bookmaker_name = _extract_market_total_from_event(matched)

    sample = OddsSample(
        market_total=market_total,
        bookmaker=bookmaker_name,
        raw={"event": matched},
    )
    used = market_total is not None
    return {"used": used, **asdict(sample)}


# ================================================================
# Public API
# ================================================================
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
            "[FAZ23-DATAHUB-DEBUG] family=%s api.used=%s odds.used=%s league_total=%s team_total=%s market_total=%s",
            family,
            bool(api_sports_block and api_sports_block.get("used")),
            bool(odds_block and odds_block.get("used")),
            (api_sports_block.get("league_total_baseline") if api_sports_block else None),
            (api_sports_block.get("team_total_baseline") if api_sports_block else None),
            (odds_block.get("market_total") if odds_block else None),
        )
    except Exception as _e:
        log.warning("[FAZ23-DATAHUB-DEBUG] failed: %s", _e)

    has_odds = bool(odds_block and odds_block.get("used") and odds_block.get("market_total") is not None)

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
