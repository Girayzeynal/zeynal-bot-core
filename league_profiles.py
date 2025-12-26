# config/league_profiles.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict


@dataclass(frozen=True)
class LeagueProfile:
    key: str                   # internal key (EUROLEAGUE, NBA, ...)
    name: str                  # human label
    api_sport_key: Optional[str]  # TheOddsAPI sport_key (if supported)
    tier: str                  # ELITE / MAJOR / REGIONAL
    provider: str              # "theoddsapi" | "api_basketball" | "manual"
    notes: str = ""


# ✅ The Odds API (basketball) sport_key list contains:
# basketball_euroleague, basketball_nba, basketball_wnba, basketball_ncaab, basketball_nbl
# (plus preseason variants etc. but core keys above are enough for production mapping)
# Source: The Odds API sports list. 1

LEAGUE_PROFILES: Dict[str, LeagueProfile] = {
    # --- ELITE (global) ---
    "NBA": LeagueProfile(
        key="NBA",
        name="NBA",
        api_sport_key="basketball_nba",
        tier="ELITE",
        provider="theoddsapi",
    ),
    "EUROLEAGUE": LeagueProfile(
        key="EUROLEAGUE",
        name="EuroLeague",
        api_sport_key="basketball_euroleague",
        tier="ELITE",
        provider="theoddsapi",
    ),

    # --- ELITE-ish / top ecosystems ---
    "WNBA": LeagueProfile(
        key="WNBA",
        name="WNBA",
        api_sport_key="basketball_wnba",
        tier="ELITE",
        provider="theoddsapi",
    ),
    "NCAAB": LeagueProfile(
        key="NCAAB",
        name="NCAA Men (NCAAB)",
        api_sport_key="basketball_ncaab",
        tier="MAJOR",
        provider="theoddsapi",
    ),
    "NBL": LeagueProfile(
        key="NBL",
        name="Australia NBL",
        api_sport_key="basketball_nbl",
        tier="MAJOR",
        provider="theoddsapi",
    ),

    # --- ELITE club leagues (NOT in The Odds API basketball list right now) ---
    # Bunları yine lig profiline ekliyoruz; market için provider "api_basketball" veya "manual"
    "ACB": LeagueProfile(
        key="ACB",
        name="Spain Liga ACB",
        api_sport_key=None,
        tier="ELITE",
        provider="api_basketball",
        notes="The Odds API basketball list does not include ACB sport_key; use api-basketball or manual mapping.",
    ),
    "TURKEY_BSL": LeagueProfile(
        key="TURKEY_BSL",
        name="Turkey BSL (Super Ligi)",
        api_sport_key=None,
        tier="ELITE",
        provider="api_basketball",
    ),
    "ITALY_SERIE_A": LeagueProfile(
        key="ITALY_SERIE_A",
        name="Italy Lega Basket Serie A",
        api_sport_key=None,
        tier="ELITE",
        provider="api_basketball",
    ),
    "GREECE_A1": LeagueProfile(
        key="GREECE_A1",
        name="Greece A1 / Basket League",
        api_sport_key=None,
        tier="ELITE",
        provider="api_basketball",
    ),
    "FRANCE_PROA": LeagueProfile(
        key="FRANCE_PROA",
        name="France Pro A (LNB Elite)",
        api_sport_key=None,
        tier="MAJOR",
        provider="api_basketball",
    ),
    "GERMANY_BBL": LeagueProfile(
        key="GERMANY_BBL",
        name="Germany BBL",
        api_sport_key=None,
        tier="MAJOR",
        provider="api_basketball",
    ),
    "ABA": LeagueProfile(
        key="ABA",
        name="ABA Adriatic League",
        api_sport_key=None,
        tier="MAJOR",
        provider="api_basketball",
    ),
    "EUROCUP": LeagueProfile(
        key="EUROCUP",
        name="EuroCup",
        api_sport_key=None,
        tier="MAJOR",
        provider="api_basketball",
    ),

    # --- BIG leagues outside EU/US ---
    "CBA": LeagueProfile(
        key="CBA",
        name="China CBA",
        api_sport_key=None,
        tier="MAJOR",
        provider="api_basketball",
    ),
    "BSL_JAPAN": LeagueProfile(
        key="BSL_JAPAN",
        name="Japan B.League",
        api_sport_key=None,
        tier="MAJOR",
        provider="api_basketball",
    ),
}

# Convenience: only TheOddsAPI-supported keys (what you asked: API_SPORT_KEY list)
API_SPORT_KEYS = {
    k: v.api_sport_key
    for k, v in LEAGUE_PROFILES.items()
    if v.api_sport_key
}
