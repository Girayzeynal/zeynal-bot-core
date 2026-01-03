# league_profiles.py
from dataclasses import dataclass


@dataclass(frozen=True)
class LeagueProfile:
    # ---- identity
    name: str

    # ---- legacy / compatibility (DO NOT REMOVE)
    pace_scale: float
    volatility_floor: float
    volatility_ceil: float
    band_hw_total: int
    band_hw_team: int
    market_weight: float
    market_required: bool
    live_weight: float
    garbage_time_factor: float

    # ---- ANALYTIC PARAMETERS (FAZ-13 CORE)
    pace_ref: float          # league reference pace
    beta_pace: float         # μ adjustment per pace delta
    beta_matchup: float      # μ adjustment per offense-defense mismatch
    k_sigma: float           # band half-width = k * σ


LEAGUE_PROFILES = {
    "NBA": LeagueProfile(
        name="NBA",

        # legacy
        pace_scale=1.00,
        volatility_floor=7.0,
        volatility_ceil=13.0,
        band_hw_total=5,
        band_hw_team=4,
        market_weight=0.85,
        market_required=True,
        live_weight=0.80,
        garbage_time_factor=1.15,

        # analytic
        pace_ref=100.0,
        beta_pace=0.90,
        beta_matchup=0.35,
        k_sigma=1.00,
    ),

    "EUROLEAGUE": LeagueProfile(
        name="EUROLEAGUE",

        # legacy
        pace_scale=0.92,
        volatility_floor=7.0,
        volatility_ceil=11.0,
        band_hw_total=6,
        band_hw_team=4,
        market_weight=0.55,
        market_required=False,
        live_weight=0.60,
        garbage_time_factor=1.05,

        # analytic
        pace_ref=96.0,
        beta_pace=0.75,
        beta_matchup=0.30,
        k_sigma=0.95,
    ),

    "TBL": LeagueProfile(
        name="TBL",

        # legacy
        pace_scale=0.98,
        volatility_floor=7.5,
        volatility_ceil=12.0,
        band_hw_total=6,
        band_hw_team=4,
        market_weight=0.50,
        market_required=False,
        live_weight=0.55,
        garbage_time_factor=1.05,

        # analytic
        pace_ref=97.0,
        beta_pace=0.70,
        beta_matchup=0.28,
        k_sigma=0.95,
    ),

    "FIBA": LeagueProfile(
        name="FIBA",

        # legacy
        pace_scale=0.95,
        volatility_floor=6.5,
        volatility_ceil=10.0,
        band_hw_total=5,
        band_hw_team=4,
        market_weight=0.40,
        market_required=False,
        live_weight=0.50,
        garbage_time_factor=1.00,

        # analytic
        pace_ref=94.0,
        beta_pace=0.65,
        beta_matchup=0.25,
        k_sigma=0.90,
    ),
}


def get_league_profile(league: str) -> LeagueProfile:
    key = (league or "").upper().strip()
    return LEAGUE_PROFILES.get(key, LEAGUE_PROFILES["EUROLEAGUE"]) 
