# -*- coding: utf-8 -*-
"""
FAZ-23 DataHub

Dış API'lerden maç bağlamı ve total bazlı özetleri toplar.
Şu anda:
- API-SPORTS Basketball (API_BASK_KEY)
- Odds API (ODDS_API_KEY)  → sadece ana total çizgisi

Amaç:
- Tek giriş noktası: fetch_match_totals(league, date_str, home, away)
- Bu fonksiyon ASLA exception fırlatmaz, her şeyi log'lar.
- Dönen dict, faz13_orchestrator içinden meta23 / baseline için kullanılır.
"""

import os
import logging
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional, List

import requests

log = logging.getLogger(__name__)

API_BASK_BASE = os.getenv("API_BASK_BASE", "https://v1.basketball.api-sports.io")
ODDS_API_BASE = os.getenv("ODDS_API_BASE", "https://api.the-odds-api.com/v4/sports")


# ---------------------------------------------------------------
# Basit modeller
# ---------------------------------------------------------------

@dataclass
class TeamSample:
    provider: str
    team: str
    games: int
    pts_for_avg: Optional[float] = None
    pts_against_avg: Optional[float] = None


@dataclass
class OddsSample:
    provider: str
    market_total: Optional[float] = None
    bookmaker: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


@dataclass
class Faz23TotalsContext:
    league: str
    date: str
    home: str
    away: str
    family: str
    league_total_baseline: Optional[float]
    team_total_baseline: Optional[float]
    home_sample: Optional[Dict[str, Any]]
    away_sample: Optional[Dict[str, Any]]
    odds: Optional[Dict[str, Any]]
    raw: Dict[str, Any]


# ---------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------

def _safe_get(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: float = 5.0,
) -> Dict[str, Any]:
    headers = headers or {}
    params = params or {}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=timeout)
    except Exception as e:
        log.warning("FAZ23 DataHub HTTP error %s %s: %s", url, params, e)
        return {"ok": False, "error": str(e)}

    try:
        data = resp.json()
    except Exception:
        text = getattr(resp, "text", "")[:500]
        log.warning("FAZ23 DataHub non-JSON response %s (%s): %s", url, resp.status_code, text)
        return {"ok": False, "status": resp.status_code, "text": text}

    return {"ok": True, "status": resp.status_code, "data": data}


def _detect_family(league: str) -> str:
    l = (league or "").lower()
    if "nba" in l:
        return "NBA"
    if "euroleague" in l or "euro league" in l:
        return "EUROLEAGUE"
    if "eurocup" in l:
        return "EUROCUP"
    if "bsl" in l or "türkiye" in l or "turkey" in l:
        return "EURO_MID"
    if "fiba" in l or "world cup" in l or "eurobasket" in l:
        return "NATIONAL"
    return "GENERICMID"


def _api_basketball_headers() -> Optional[Dict[str, str]]:
    key = os.getenv("API_BASK_KEY")
    if not key:
        return None
    # API-Sports doğrudan kullanım + RapidAPI senaryosunu aynı anda destekle
    return {
        "x-apisports-key": key,
        "x-rapidapi-key": key,
        "x-rapidapi-host": "v1.basketball.api-sports.io",
    }


def _norm_name(name: str) -> str:
    return (
        (name or "")
        .lower()
        .replace(".", "")
        .replace("-", " ")
        .replace("_", " ")
        .strip()
    )


def _avg(values: List[float]) -> Optional[float]:
    return round(sum(values) / len(values), 2) if values else None


# ---------------------------------------------------------------
# API-SPORTS BASKETBALL → Lig & takım bazlı total tahmini
# ---------------------------------------------------------------

def _fetch_api_basketball_totals(
    date_str: str,
    home: str,
    away: str,
) -> Dict[str, Any]:
    """
    Basit strateji:
    - /games?date=YYYY-MM-DD ile o gündeki tüm maçları çek
    - Lig ortalama totalini hesapla
    - Home & Away takımının oynadığı maçlardan hücum/savunma ortalamaları çıkar
    - Bunlardan "team_total_baseline" üret
    """
    headers = _api_basketball_headers()
    if not headers:
        return {"used": False, "reason": "NO_API_BASK_KEY"}

    url = f"{API_BASK_BASE}/games"
    params = {"date": date_str}

    resp = _safe_get(url, headers=headers, params=params)
    if not resp.get("ok"):
        return {"used": False, "reason": "HTTP_ERROR", "raw": resp}

    data = resp.get("data") or {}
    games = data.get("response") or data.get("games") or []
    if not isinstance(games, list):
        return {"used": False, "reason": "INVALID_RESPONSE", "raw": data}

    h_norm = _norm_name(home)
    a_norm = _norm_name(away)

    league_totals: List[float] = []
    home_for: List[float] = []
    home_against: List[float] = []
    away_for: List[float] = []
    away_against: List[float] = []

    for g in games:
        teams = g.get("teams") or {}
        t_home = teams.get("home") or {}
        t_away = teams.get("away") or {}

        name_home = _norm_name(str(t_home.get("name", "")))
        name_away = _norm_name(str(t_away.get("name", "")))

        scores = g.get("scores") or {}
        s_home = scores.get("home") or {}
        s_away = scores.get("away") or {}

        # Bazı API-Sports örnekleri 'points', bazıları 'total' alanını kullanıyor
        ph = s_home.get("points") or s_home.get("total")
        pa = s_away.get("points") or s_away.get("total")

        try:
            ph_f = float(ph)
            pa_f = float(pa)
        except Exception:
            continue

        total = ph_f + pa_f
        league_totals.append(total)

        # Home takım istatistikleri (hem iç saha hem deplasman say)
        if h_norm and (h_norm in name_home or name_home in h_norm):
            home_for.append(ph_f)
            home_against.append(pa_f)
        if h_norm and (h_norm in name_away or name_away in h_norm):
            home_for.append(pa_f)
            home_against.append(ph_f)

        # Away takım istatistikleri
        if a_norm and (a_norm in name_home or name_home in a_norm):
            away_for.append(ph_f)
            away_against.append(pa_f)
        if a_norm and (a_norm in name_away or name_away in a_norm):
            away_for.append(pa_f)
            away_against.append(ph_f)

    league_avg = _avg(league_totals)

    home_sample = TeamSample(
        provider="API_BASKETBALL",
        team=home,
        games=len(home_for) or len(home_against),
        pts_for_avg=_avg(home_for),
        pts_against_avg=_avg(home_against),
    )
    away_sample = TeamSample(
        provider="API_BASKETBALL",
        team=away,
        games=len(away_for) or len(away_against),
        pts_for_avg=_avg(away_for),
        pts_against_avg=_avg(away_against),
    )

    team_baseline = None
    if home_sample.pts_for_avg is not None and away_sample.pts_for_avg is not None:
        # Basit formul:
        #  - hücum ortalama toplamına %60
        #  - savunma (rakibe verilen sayı) toplamına %40
        off_sum = home_sample.pts_for_avg + away_sample.pts_for_avg
        def_sum = (home_sample.pts_against_avg or home_sample.pts_for_avg) + (
            away_sample.pts_against_avg or away_sample.pts_for_avg
        )
        team_baseline = round(off_sum * 0.6 + def_sum * 0.4, 1)

    return {
        "used": True,
        "league_total_baseline": league_avg,
        "team_total_baseline": team_baseline,
        "home_sample": asdict(home_sample),
        "away_sample": asdict(away_sample),
        "raw": data,
    }


# ---------------------------------------------------------------
# ODDS API → ana total çizgisi (opsiyonel)
# ---------------------------------------------------------------

def _fetch_odds_totals(
    family: str,
    home: str,
    away: str,
) -> Optional[Dict[str, Any]]:
    """
    Odds-API (v4) yapısına göre ana total çizgisini okumaya çalışır.

    Çalışmaması durumunda hiçbir şeyi bozmaz, sadece "used": False döndürür.
    """
    key = os.getenv("ODDS_API_KEY")
    if not key:
        return None

    # Sport kodu env'den override edilebilir
    sport_key = os.getenv("ODDS_SPORT_KEY")
    if not sport_key:
        sport_key = "basketball_nba" if family == "NBA" else "basketball"

    url = f"{ODDS_API_BASE}/{sport_key}/odds"
    params = {
        "apiKey": key,
        "regions": os.getenv("ODDS_REGIONS", "eu,uk"),
        "markets": "totals",
        "oddsFormat": "decimal",
    }

    resp = _safe_get(url, headers={}, params=params)
    if not resp.get("ok"):
        return {"used": False, "raw": resp}

    data = resp.get("data") or []
    if not isinstance(data, list):
        return {"used": False, "raw": data}

    h_norm = _norm_name(home)
    a_norm = _norm_name(away)

    lines: List[float] = []
    bookmaker_name = None

    for event in data:
        teams = [str(t) for t in event.get("teams", [])]
        teams_joined = _norm_name(" ".join(teams))
        if h_norm not in teams_joined and a_norm not in teams_joined:
            continue

        for book in event.get("bookmakers", []):
            bookmaker_name = bookmaker_name or book.get("title") or book.get("key")
            for market in book.get("markets", []):
                if market.get("key") != "totals":
                    continue
                for outcome in market.get("outcomes", []):
                    point = outcome.get("point")
                    try:
                        lines.append(float(point))
                    except Exception:
                        continue

    if not lines:
        return {"used": False, "raw": data}

    avg_line = round(sum(lines) / len(lines), 1)

    odds_sample = OddsSample(
        provider="ODDS_API",
        market_total=avg_line,
        bookmaker=bookmaker_name,
        raw=None,
    )

    return {
        "used": True,
        "market_total": avg_line,
        "bookmaker": bookmaker_name,
        "sample": asdict(odds_sample),
        "raw": data,
    }


# ---------------------------------------------------------------
# Public API
# ---------------------------------------------------------------

def fetch_match_totals(
    league: str,
    date_str: str,
    home: str,
    away: str,
) -> Dict[str, Any]:
    """
    FAZ-13 orchestrator tarafından çağrılan ana fonksiyon.

    Çıkış:
        {
          'league': ...,
          'date': ...,
          'home': ...,
          'away': ...,
          'family': 'NBA' | 'EUROLEAGUE' | ...,
          'league_total_baseline': float | None,
          'team_total_baseline': float | None,
          'home_sample': {...} | None,
          'away_sample': {...} | None,
          'odds': {...} | None,
          'raw': {
              'api_basketball': ...,
              'odds_api': ...,
          }
        }
    """
    family = _detect_family(league)

    api_bask_block: Optional[Dict[str, Any]] = None
    odds_block: Optional[Dict[str, Any]] = None

    # API-Sports Basketball
    try:
        api_bask_block = _fetch_api_basketball_totals(
            date_str=date_str,
            home=home,
            away=away,
        )
    except Exception as e:
        log.warning("FAZ23 DataHub API-BASK exception: %s", e)

    # Odds API (opsiyonel)
    try:
        odds_block = _fetch_odds_totals(
            family=family,
            home=home,
            away=away,
        )
    except Exception as e:
        log.warning("FAZ23 DataHub ODDS exception: %s", e)

    league_total_baseline: Optional[float] = None
    team_total_baseline: Optional[float] = None
    home_sample_dict: Optional[Dict[str, Any]] = None
    away_sample_dict: Optional[Dict[str, Any]] = None
    odds_sample_dict: Optional[Dict[str, Any]] = None

    raw: Dict[str, Any] = {}

    if api_bask_block:
        raw["api_basketball"] = api_bask_block.get("raw")
        league_total_baseline = api_bask_block.get("league_total_baseline")
        team_total_baseline = api_bask_block.get("team_total_baseline")
        home_sample_dict = api_bask_block.get("home_sample")
        away_sample_dict = api_bask_block.get("away_sample")

    if odds_block:
    raw["odds_api"] = odds_block.get("raw")
    # sample bazen None oluyor; biz komple bloğu döndürelim ki used/market_total görünsün
    odds_sample_dict = odds_block

    ...
    odds=odds_sample_dict,

    ctx = Faz23TotalsContext(
        league=league,
        date=date_str,
        home=home,
        away=away,
        family=family,
        league_total_baseline=league_total_baseline,
        team_total_baseline=team_total_baseline,
        home_sample=home_sample_dict,
        away_sample=away_sample_dict,
        odds=odds_sample_dict,
        raw=raw,
    )

    return asdict(ctx)
