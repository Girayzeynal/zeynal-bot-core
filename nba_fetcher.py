"""
FAZ-4 – NBA Fetcher (Real Mode Altyapısı + Dummy Mod)

Bu sürüm:
- Dummy veri üretir (FAZ-4 motor işleri için)
- ESPN gerçek API test fonksiyonu içerir (/nba_raw)
- Hata korumalı HTTP istemcisi (safe_get) içerir
- NBAGameState modellerine uygun dummy yapı döndürür
- NBA_REAL_MODE=1 olduğunda ESPN scoreboard verisini NBAGameState’e çevirir
"""

import os
import requests
from datetime import datetime, timedelta, timezone
from typing import List

from nba_config import (
    NBA_LEAGUE_CODE,
    CURRENT_SEASON,
)

from nba_models import (
    NBAGameState,
    NBATeamStatsLite,
)

# ---------------------------------------------------------
#  MOD SEÇİMİ (DUMMY vs GERÇEK)
# ---------------------------------------------------------

NBA_REAL_MODE = os.getenv("NBA_REAL_MODE", "0") == "1"


# ---------------------------------------------------------
#  GERÇEK API İSTEĞİ İÇİN GÜVENLİ HTTP İSTEMCİSİ
# ---------------------------------------------------------

def safe_get(url: str):
    """
    Güvenli GET isteği.
    - Hata durumunda botun çökmesini engeller
    - JSON dönmeye çalışır
    - ESPN HTML hata sayfası gibi durumlarda raw text döner
    """
    try:
        r = requests.get(url, timeout=8)
        r.raise_for_status()

        try:
            return r.json()
        except Exception:
            return {"error": "Invalid JSON", "raw": r.text}

    except Exception as e:
        return {"error": str(e), "raw": None}


# ---------------------------------------------------------
#  ESPN — GERÇEK NBA SCOREBOARD (HAM VERİ)
# ---------------------------------------------------------

def fetch_nba_schedule_real():
    """
    ESPN NBA scoreboard endpoint.
    Bu fonksiyon henüz NBAGameState formatına dönüştürmüyor.
    /nba_raw komutu bu fonksiyonu kullanır.
    """
    url = "https://site.api.espn.com/apis/v2/sports/basketball/nba/scoreboard"
    data = safe_get(url)
    return data


# ---------------------------------------------------------
#  ESPN → NBAGameState ÇEVİRİCİ (GENEL)
# ---------------------------------------------------------

def _parse_espn_scoreboard_to_games(data) -> List[NBAGameState]:
    """
    ESPN scoreboard JSON'unu NBAGameState listesine çevirir.

    Çok agresif, ama güvenli:
    - Alanlar yoksa default değerler kullanır
    - Hiçbir durumda exception fırlatıp botu düşürmez
    """
    games: List[NBAGameState] = []

    if not isinstance(data, dict):
        return games

    events = data.get("events", []) or []

    for ev in events:
        try:
            ev_id = ev.get("id", "unknown")
            ev_date = ev.get("date")
            if ev_date:
                try:
                    tipoff_utc = datetime.fromisoformat(ev_date.replace("Z", "+00:00"))
                except Exception:
                    tipoff_utc = datetime.now(timezone.utc)
            else:
                tipoff_utc = datetime.now(timezone.utc)

            status_info = (ev.get("status") or {}).get("type", {}) or {}
            raw_state = (status_info.get("state") or "").lower()
            raw_desc = (status_info.get("description") or "").lower()

            if "pre" in raw_state or "pre" in raw_desc:
                status = "scheduled"
            elif "in" in raw_state or "live" in raw_desc:
                status = "live"
            elif "post" in raw_state or "final" in raw_desc:
                status = "finished"
            else:
                status = raw_state or "unknown"

            competitions = ev.get("competitions", []) or []
            if not competitions:
                continue

            comp = competitions[0]
            competitors = comp.get("competitors", []) or []

            home_team_code = "HOME"
            away_team_code = "AWAY"
            home_stats = None
            away_stats = None

            for c in competitors:
                team = c.get("team", {}) or {}
                code = (
                    team.get("abbreviation")
                    or team.get("shortDisplayName")
                    or team.get("name")
                    or "UNK"
                )
                side = (c.get("homeAway") or "").lower()
                score_str = c.get("score", "0")
                try:
                    pts = float(score_str)
                except Exception:
                    pts = 0.0

                # Şimdilik sadece skor üzerinden dummy istatistik üretelim
                stats = NBATeamStatsLite(
                    team_code=code,
                    pts=pts,
                    reb=0,
                    ast=0,
                    tov=0,
                    fg_pct=0.0,
                    fg3_pct=0.0,
                    ft_pct=0.0,
                    pace_est=None,
                )

                if side == "home":
                    home_team_code = code
                    home_stats = stats
                else:
                    away_team_code = code
                    away_stats = stats

            game = NBAGameState(
                league=NBA_LEAGUE_CODE,
                game_id=ev_id,
                season=CURRENT_SEASON,
                status=status,
                tipoff_utc=tipoff_utc,
                home_team=home_team_code,
                away_team=away_team_code,
                home_stats=home_stats,
                away_stats=away_stats,
                spread_home=None,
                spread_away=None,
                total_points=None,
            )
            games.append(game)

        except Exception:
            # Tekil event patlarsa tüm listeyi çöpe atmamak için yutuyoruz
            continue

    return games


def _filter_by_status(games: List[NBAGameState], wanted: str) -> List[NBAGameState]:
    wanted = wanted.lower()
    return [g for g in games if (g.status or "").lower() == wanted]


def _fetch_games_real_by_status(target_status: str) -> List[NBAGameState]:
    """
    Scoreboard'tan tüm maçları çekip statüye göre filtreler.
    """
    data = fetch_nba_schedule_real()
    if not isinstance(data, dict):
        return []

    if data.get("error"):
        # Hata varsa boş liste dön – bot düşmesin
        return []

    all_games = _parse_espn_scoreboard_to_games(data)
    return _filter_by_status(all_games, target_status)


# ---------------------------------------------------------
#  FAZ-4 MOTOR İÇİN DUMMY VERİLER (ESKİ DAVRANIŞ)
# ---------------------------------------------------------

def _fetch_nba_today_games_dummy() -> List[NBAGameState]:
    """
    FAZ-4 test modu:
    Bugünkü planlanan maçlar için dummy veri döner.
    """
    game_id = "20250101-LAL-BOS"
    tipoff_utc = datetime.now(timezone.utc) + timedelta(hours=3)

    game = NBAGameState(
        league=NBA_LEAGUE_CODE,
        game_id=game_id,
        season=CURRENT_SEASON,
        status="scheduled",
        tipoff_utc=tipoff_utc,
        home_team="LAL",
        away_team="BOS",
        home_stats=None,
        away_stats=None,
        spread_home=None,
        spread_away=None,
        total_points=None,
    )

    return [game]


def _fetch_nba_live_games_dummy() -> List[NBAGameState]:
    """
    FAZ-4 test modu:
    Canlı maçlar için dummy veri.
    """
    game_id = "20250101-MIA-NYK"
    tipoff_utc = datetime.now(timezone.utc) - timedelta(hours=1)

    home = NBATeamStatsLite(
        team_code="MIA",
        pts=54,
        reb=22,
        ast=16,
        tov=7,
        fg_pct=0.48,
        fg3_pct=0.37,
        ft_pct=0.82,
        pace_est=99.5,
    )

    away = NBATeamStatsLite(
        team_code="NYK",
        pts=50,
        reb=18,
        ast=14,
        tov=9,
        fg_pct=0.45,
        fg3_pct=0.32,
        ft_pct=0.79,
        pace_est=98.2,
    )

    game = NBAGameState(
        league=NBA_LEAGUE_CODE,
        game_id=game_id,
        season=CURRENT_SEASON,
        status="live",
        tipoff_utc=tipoff_utc,
        home_team="MIA",
        away_team="NYK",
        home_stats=home,
        away_stats=away,
        spread_home=None,
        spread_away=None,
        total_points=None,
    )

    return [game]


def _fetch_nba_finished_games_dummy() -> List[NBAGameState]:
    """
    FAZ-4 test modu:
    Bitmiş maçlar için dummy veri.
    """
    game_id = "20250101-GSW-DEN"
    tipoff_utc = datetime.now(timezone.utc) - timedelta(hours=4)

    home = NBATeamStatsLite(
        team_code="GSW",
        pts=112,
        reb=41,
        ast=28,
        tov=14,
        fg_pct=0.46,
        fg3_pct=0.39,
        ft_pct=0.87,
        pace_est=101.2,
    )

    away = NBATeamStatsLite(
        team_code="DEN",
        pts=118,
        reb=44,
        ast=25,
        tov=12,
        fg_pct=0.49,
        fg3_pct=0.38,
        ft_pct=0.79,
        pace_est=100.8,
    )

    game = NBAGameState(
        league=NBA_LEAGUE_CODE,
        game_id=game_id,
        season=CURRENT_SEASON,
        status="finished",
        tipoff_utc=tipoff_utc,
        home_team="GSW",
        away_team="DEN",
        home_stats=home,
        away_stats=away,
        spread_home=None,
        spread_away=None,
        total_points=None,
    )

    return [game]


# ---------------------------------------------------------
#  DIŞARIDAN KULLANILACAK ARAYÜZ (PUBLIC API)
# ---------------------------------------------------------

def fetch_nba_today_games() -> List[NBAGameState]:
    """
    Dış dünyaya tek fonksiyon.
    NBA_REAL_MODE=1 ise gerçek scoreboard'tan,
    değilse dummy veriden beslenir.
    """
    if NBA_REAL_MODE:
        return _fetch_games_real_by_status("scheduled")
    return _fetch_nba_today_games_dummy()


def fetch_nba_live_games() -> List[NBAGameState]:
    """
    /simulate_nba komutu bunu kullanıyor.
    """
    if NBA_REAL_MODE:
        return _fetch_games_real_by_status("live")
    return _fetch_nba_live_games_dummy()


def fetch_nba_finished_games() -> List[NBAGameState]:
    """
    Bitmiş maç analizi için.
    """
    if NBA_REAL_MODE:
        return _fetch_games_real_by_status("finished")
    return _fetch_nba_finished_games_dummy()
