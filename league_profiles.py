"""
league_profiles.py
====================

This module defines `LeagueProfile` data structures and exposes a registry for
basketball leagues supported by the bot.  It also provides a convenience
function to look up the configuration for a given league.  The information
here drives several downstream analytics engines, including scoring and
market enrichment.

Each `LeagueProfile` contains:

* **key** – a short, canonical identifier (e.g. ``NBA``, ``EUROLEAGUE``).
* **name** – a human‑readable name.
* **api_sport_key** – the sport key used by The Odds API (or ``None`` if
  unsupported).
* **tier** – a qualitative class such as ``ELITE``, ``MAJOR`` or ``REGIONAL``.
* **provider** – where to source team statistics from (``theoddsapi``,
  ``api_basketball``, or ``manual``).
* **band_hw_total** – the expected half‑width of the total points band.  The
  Faz22Engine uses this to infer a baseline confidence interval.
* **market_weight** – the relative weight applied to market agreement when
  computing meta scores.  Values range from 0 (ignore) to 1 (full).
* **market_required** – whether the league requires market data for
  confidence scoring.
* **notes** – free‑form description or caveats.

Use the ``get_league_profile`` function to obtain a profile given an
arbitrary league key.  Unknown leagues fall back to a generic profile.
"""

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class LeagueProfile:
    """Configuration data for a basketball league."""

    key: str
    name: str
    api_sport_key: Optional[str]
    tier: str
    provider: str
    band_hw_total: float = 6.0
    market_weight: float = 0.5
    market_required: bool = False
    notes: str = ""


# ---------------------------------------------------------------------------
# League registry
#
# The dictionary below maps league identifiers (case‑insensitive) to
# LeagueProfile instances.  Adjust these values as you add new leagues or
# refine your calibration.
# ---------------------------------------------------------------------------
LEAGUE_PROFILES: Dict[str, LeagueProfile] = {
    # Global / premier leagues
    "NBA": LeagueProfile(
        key="NBA",
        name="NBA",
        api_sport_key="basketball_nba",
        tier="ELITE",
        provider="theoddsapi",
        band_hw_total=6.0,
        market_weight=0.6,
        market_required=False,
    ),
    "EUROLEAGUE": LeagueProfile(
        key="EUROLEAGUE",
        name="EuroLeague",
        api_sport_key="basketball_euroleague",
        tier="ELITE",
        provider="theoddsapi",
        band_hw_total=6.0,
        market_weight=0.6,
        market_required=False,
    ),
    # Other notable leagues
    "WNBA": LeagueProfile(
        key="WNBA",
        name="WNBA",
        api_sport_key="basketball_wnba",
        tier="ELITE",
        provider="theoddsapi",
        band_hw_total=5.5,
        market_weight=0.5,
        market_required=False,
    ),
    "NCAAB": LeagueProfile(
        key="NCAAB",
        name="NCAA Men (NCAAB)",
        api_sport_key="basketball_ncaab",
        tier="MAJOR",
        provider="theoddsapi",
        band_hw_total=7.0,
        market_weight=0.4,
        market_required=False,
    ),
    "NBL": LeagueProfile(
        key="NBL",
        name="Australia NBL",
        api_sport_key="basketball_nbl",
        tier="MAJOR",
        provider="theoddsapi",
        band_hw_total=6.5,
        market_weight=0.4,
        market_required=False,
    ),
    # Elite club leagues not covered by The Odds API
    "ACB": LeagueProfile(
        key="ACB",
        name="Spain Liga ACB",
        api_sport_key=None,
        tier="ELITE",
        provider="api_basketball",
        notes="The Odds API does not provide a sport_key for ACB; use api_basketball or manual sources.",
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
    # Big leagues outside Europe/US
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


# Build a convenience mapping for sports keys directly supported by The Odds API
API_SPORT_KEYS: Dict[str, str] = {
    k: v.api_sport_key for k, v in LEAGUE_PROFILES.items() if v.api_sport_key
}


def get_league_profile(key: str) -> LeagueProfile:
    """Return the LeagueProfile for `key` (case‑insensitive).

    Unknown keys fall back to a generic profile with neutral parameters.
    """
    if not key:
        return LeagueProfile(
            key="UNKNOWN",
            name="Unknown League",
            api_sport_key=None,
            tier="REGIONAL",
            provider="manual",
            band_hw_total=6.0,
            market_weight=0.5,
            market_required=False,
        )
    prof = LEAGUE_PROFILES.get(key.upper())
    if prof:
        return prof
    # default fallback for unrecognised leagues
    return LeagueProfile(
        key=key.upper(),
        name=key,
        api_sport_key=None,
        tier="REGIONAL",
        provider="manual",
        band_hw_total=6.0,
        market_weight=0.5,
        market_required=False,
    ) 
