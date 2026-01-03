# league_profiles.py
from dataclasses import dataclass

@dataclass(frozen=True)
class LeagueProfile:
    name: str
    pace_scale: float
    volatility_floor: float
    volatility_ceil: float
    band_hw_total: int
    band_hw_team: int
    market_weight: float
    market_required: bool
    live_weight: float
    garbage_time_factor: float


LEAGUE_PROFILES = {
    "NBA": LeagueProfile(
        name="NBA",
        pace_scale=1.00,              # 🔴 GERÇEKÇİ AYAR (1.10 YANLIŞTI)
        volatility_floor=7.0,
        volatility_ceil=13.0,
        band_hw_total=5,
        band_hw_team=4,
        market_weight=0.85,
        market_required=True,
        live_weight=0.80,
        garbage_time_factor=1.15,
    ),
    "EUROLEAGUE": LeagueProfile(
        name="EUROLEAGUE",
        pace_scale=0.92,
        volatility_floor=7.0,
        volatility_ceil=11.0,
        band_hw_total=6,
        band_hw_team=4,
        market_weight=0.55,
        market_required=False,
        live_weight=0.60,
        garbage_time_factor=1.05,
    ),
    "TBL": LeagueProfile(
        name="TBL",
        pace_scale=0.98,
        volatility_floor=7.5,
        volatility_ceil=12.0,
        band_hw_total=6,
        band_hw_team=4,
        market_weight=0.50,
        market_required=False,
        live_weight=0.55,
        garbage_time_factor=1.05,
    ),
    "FIBA": LeagueProfile(
        name="FIBA",
        pace_scale=0.95,
        volatility_floor=6.5,
        volatility_ceil=10.0,
        band_hw_total=5,
        band_hw_team=4,
        market_weight=0.40,
        market_required=False,
        live_weight=0.50,
        garbage_time_factor=1.00,
    ),
}

def get_league_profile(league: str) -> LeagueProfile:
    key = (league or "").upper().strip()
    return LEAGUE_PROFILES.get(key, LEAGUE_PROFILES["EUROLEAGUE"]) 
