"""
FAZ-4 – NBA Fetcher (Tam İskelet + Gerçek API Test Fonksiyonu)

Bu sürüm:
- Dummy veri üretir (FAZ-4 motor işleri için)
- ESPN gerçek API test fonksiyonu içerir (/nba_raw)
- Hata korumalı HTTP istemcisi (safe_get) içerir
- NBAGameState modellerine uygun dummy yapı döndürür
"""

import requests
from datetime import datetime, timedelta, timezone
from typing import List

from nba_config import (
    NBA_LEAGUE_CODE,
    CURRENT_SEASON
)

from nba_models import (
    NBAGameState,
    NBATeamStatsLite
)


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
#  ESPN — GERÇEK NBA VERİSİ ÇEKME (TEST MODU)
# ---------------------------------------------------------

def fetch_nba_schedule_real():
    """
    ESPN NBA scoreboard endpoint.
    Bu fonksiyon henüz NBAGameState formatına dönüştürmüyor.
    Ama gerçek verinin gelip gelmediğini test etmek için kritik.
    /nba_raw komutu bu fonksiyonu kullanır.
    """
    url = "https://site.api.espn.com/apis/v2/sports/basketball/nba/scoreboard"
    data = safe_get(url)
    return data



# ---------------------------------------------------------
#  FAZ-4 MOTOR İÇİN DUMMY VERİLER (TEST)
# ---------------------------------------------------------

def fetch_nba_today_games() -> List[NBAGameState]:
    """
    FAZ-4 test modu:
    Bugünkü planlanan maçlar için dummy veri döner.
    Sistem akışını test etmek için kullanılır.
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
        away_stats=None
    )

    return [game]



def fetch_nba_live_games() -> List[NBAGameState]:
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
        pace_est=99.5
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
        pace_est=98.2
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
        total_points=None
    )

    return [game]



def fetch_nba_finished_games() -> List[NBAGameState]:
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
        pace_est=101.2
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
        pace_est=100.8
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
        away_stats=away
    )

    return [game]
