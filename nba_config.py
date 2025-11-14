"""
FAZ-4 – NBA Data Core Config

Bu dosya:
- NBA için temel sabitleri
- zaman dilimi ayarlarını
- sezon / lig metadata'sını
- ileride eklenecek endpoint'ler için yer tutucuları
barındırır.

Şu an API çağrısı yapmıyor, sadece yapı kuruyoruz.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional


LeagueCode = Literal["NBA"]


NBA_LEAGUE_CODE: LeagueCode = "NBA"

# İleride sezon değiştirmek kolay olsun diye buradan kontrol edeceğiz.
CURRENT_SEASON = "2024-25"

# NBA fiili zaman kuşağı – veri kaynaklarının çoğu US Eastern'i baz alıyor.
NBA_TZ = timezone(timedelta(hours=-5))  # UTC-5 (standart saat)
UTC_TZ = timezone.utc


@dataclass(slots=True)
class NBATeamMeta:
    code: str          # "LAL"
    name: str          # "Los Angeles Lakers"
    conference: str    # "West"
    division: str      # "Pacific"


@dataclass(slots=True)
class NBAGameMeta:
    game_id: str
    season: str
    home_team: str      # "LAL"
    away_team: str      # "BOS"
    tipoff_utc: datetime
    venue: Optional[str] = None


@dataclass(slots=True)
class NBAOddsSnapshot:
    game_id: str
    source: str         # "dummy" / "bookmaker_x" vs.
    created_utc: datetime
    spread_home: Optional[float] = None
    spread_away: Optional[float] = None
    total_points: Optional[float] = None
    moneyline_home: Optional[float] = None
    moneyline_away: Optional[float] = None


def to_utc(dt: datetime) -> datetime:
    """
    Girilen datetime'i (tz bilgisi varsa) UTC'ye çevirir.
    Yoksa NBA_TZ kabul eder, UTC'ye taşır.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=NBA_TZ)
    return dt.astimezone(UTC_TZ)


def from_utc_to_nba(dt_utc: datetime) -> datetime:
    """
    UTC zamanı NBA ana zaman dilimine (US Eastern) çevirir.
    FAZ-1 anayasasındaki UTC kutsal yasasıyla uyumludur.
    """
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=UTC_TZ)
    return dt_utc.astimezone(NBA_TZ)


# İleride gerçek endpoint'leri buraya dolduracağız.
# Şimdilik sadece iskelet.
@dataclass(slots=True)
class NBAEndpointConfig:
    """
    Gerçek API adresleri / parametreleri buradan yönetilecek.
    Şimdilik sadece yer tutucu alanlar.
    """
    schedule_base_url: str = "https://example.com/nba/schedule"
    boxscore_base_url: str = "https://example.com/nba/boxscore"
    odds_base_url: str = "https://example.com/nba/odds"


ENDPOINTS = NBAEndpointConfig()
