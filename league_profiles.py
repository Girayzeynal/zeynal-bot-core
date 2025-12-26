# league_profiles.py
# Central league behavior configuration
# All engines (FAZ-13 / FAZ-17 / FAZ-22 / LIVE) must read from here

from dataclasses import dataclass


@dataclass(frozen=True)
class LeagueProfile:
    name: str

    # Scoring behavior
    pace_scale: float           # tempo multiplier
    volatility_floor: float     # min sigma
    volatility_ceil: float      # max sigma

    # Prediction band control
    band_hw_total: int          # half-width of total band
    band_hw_team: int           # half-width of team band

    # Market trust (FAZ-17)
    market_weight: float        # how much market can shift FAZ-13
    market_required: bool       # if False → NO_MARKET is acceptable

    # Live behavior
    live_weight: float          # momentum importance
    garbage_time_factor: float  # blowout late-game inflation


LEAGUE_PROFILES = {

    "NBA": LeagueProfile(
        name="NBA",
        pace_scale=1.10,
        volatility_floor=8.5,
        volatility_ceil=15.0,
        band_hw_total=7,
        band_hw_team=5,
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
