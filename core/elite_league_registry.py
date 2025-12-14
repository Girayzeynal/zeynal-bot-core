# ================================================================
# 🧠 ELITE BASKETBALL CORE – LEAGUE REGISTRY
# Single source of truth for league hierarchy & permissions
# ================================================================

import os

# ================================================================
# 🔐 GLOBAL FLAGS (env controlled)
# ================================================================
ELITE_CORE_ON = os.getenv("ELITE_CORE_ON", "1") == "1"
CROSS_LEAGUE_ENRICHMENT = os.getenv("CROSS_LEAGUE_ENRICHMENT", "1") == "1"
CROSS_LEAGUE_MARKET = os.getenv("CROSS_LEAGUE_MARKET", "0") == "1"   # default OFF
FIBA_ISOLATED_MODE = os.getenv("FIBA_ISOLATED_MODE", "1") == "1"
MARKET_TEST_MODE = os.getenv("MARKET_TEST_MODE", "0") == "1"

# ================================================================
# 🧱 ELITE LEAGUE REGISTRY (CANONICAL CODES)
# ================================================================
ELITE_LEAGUE_REGISTRY = {
    # ---------------- CORE (PROFILE ONLY) ----------------
    "CORE": {
        "NBA",
        "EUROLEAGUE",
    },

    # ---------------- DOMESTIC ELITE (PRIMARY EVENTS) -----
    "DOMESTIC_ELITE": {
        "TURKEY_BSL",
        "SPAIN_ACB",
        "FRANCE_LNB",
        "GERMANY_BBL",
        "ITALY_LEGA_A",
        "GREECE_GBL",
        "ABA_ADRIATIC",
    },

    # ---------------- SECONDARY INTERNATIONAL --------------
    "SECONDARY_INTL": {
        "EUROCUP",
        "BCL",
    },

    # ---------------- FIBA (ISOLATED WORLD) ----------------
    "FIBA": {
        "FIBA_NATIONAL",
        "FIBA_QUALIFIERS",
        "FIBA_TOURNAMENT",
    },
}

# ================================================================
# 🗺️ LEAGUE ALIASES (user / api input → canonical)
# ================================================================
LEAGUE_ALIASES = {
    # ---- CORE
    "nba": "NBA",
    "euroleague": "EUROLEAGUE",
    "el": "EUROLEAGUE",

    # ---- SECONDARY INTL
    "eurocup": "EUROCUP",
    "ec": "EUROCUP",
    "bcl": "BCL",
    "champions league": "BCL",

    # ---- DOMESTIC ELITE
    "turkiye": "TURKEY_BSL",
    "türkiye": "TURKEY_BSL",
    "bsl": "TURKEY_BSL",

    "acb": "SPAIN_ACB",
    "ispanya": "SPAIN_ACB",
    "spain": "SPAIN_ACB",

    "lnb": "FRANCE_LNB",
    "fransa": "FRANCE_LNB",
    "france": "FRANCE_LNB",

    "bbl": "GERMANY_BBL",
    "almanya": "GERMANY_BBL",
    "germany": "GERMANY_BBL",

    "lega a": "ITALY_LEGA_A",
    "italya": "ITALY_LEGA_A",
    "italy": "ITALY_LEGA_A",

    "gbl": "GREECE_GBL",
    "yunanistan": "GREECE_GBL",
    "greece": "GREECE_GBL",

    "aba": "ABA_ADRIATIC",
    "adriatic": "ABA_ADRIATIC",

    # ---- FIBA
    "fiba": "FIBA_TOURNAMENT",
    "qualifiers": "FIBA_QUALIFIERS",
    "national": "FIBA_NATIONAL",
}

# ================================================================
# 🔍 NORMALIZATION
# ================================================================
def normalize_league_input(raw_league: str) -> str:
    """
    Normalize user or provider league input into canonical code.
    """
    if not raw_league:
        return ""
    key = raw_league.strip().lower()
    return LEAGUE_ALIASES.get(key, raw_league.strip())

# ================================================================
# 🧭 LEAGUE LAYER RESOLUTION
# ================================================================
def resolve_league_layer(league_code: str) -> str:
    """
    Resolve which elite layer the league belongs to.
    """
    if not league_code:
        return "UNSUPPORTED"
    for layer, leagues in ELITE_LEAGUE_REGISTRY.items():
        if league_code in leagues:
            return layer
    return "UNSUPPORTED"

# ================================================================
# 🚦 MARKET PERMISSION GATEKEEPER
# ================================================================
def market_permission(primary_layer: str) -> dict:
    """
    Decide if market (odds) can be used for this league layer.
    """
    # ---- Domestic elite: always allowed
    if primary_layer == "DOMESTIC_ELITE":
        return {
            "allowed": True,
            "confidence": "PRIMARY"
        }

    # ---- Secondary international: test only
    if primary_layer == "SECONDARY_INTL":
        if MARKET_TEST_MODE and CROSS_LEAGUE_MARKET:
            return {
                "allowed": True,
                "confidence": "SECONDARY_TEST"
            }
        return {
            "allowed": False,
            "reason": "SECONDARY_NO_MARKET"
        }

    # ---- Core leagues: profile only
    if primary_layer == "CORE":
        return {
            "allowed": False,
            "reason": "CORE_PROFILE_ONLY"
        }

    # ---- FIBA: isolated but allowed
    if primary_layer == "FIBA":
        return {
            "allowed": True,
            "confidence": "FIBA_ISOLATED"
        }

    return {
        "allowed": False,
        "reason": "UNSUPPORTED_LEAGUE"
    }

# ================================================================
# 🧠 ENRICHMENT SOURCES
# ================================================================
def enrichment_sources(primary_layer: str) -> list:
    """
    Decide which leagues can be used as profile enrichment.
    """
    if not CROSS_LEAGUE_ENRICHMENT:
        return []

    if primary_layer == "DOMESTIC_ELITE":
        return ["EUROLEAGUE", "NBA"]

    if primary_layer == "SECONDARY_INTL":
        return ["EUROLEAGUE"]

    if primary_layer == "FIBA":
        return ["FIBA_ONLY"]

    return []

# ================================================================
# 🧪 DEBUG SNAPSHOT (optional)
# ================================================================
def elite_core_snapshot(league_code: str) -> dict:
    """
    Lightweight debug snapshot for FAZ logs.
    """
    layer = resolve_league_layer(league_code)
    perm = market_permission(layer)
    return {
        "league_code": league_code,
        "layer": layer,
        "market_allowed": perm.get("allowed"),
        "market_confidence": perm.get("confidence"),
        "market_reason": perm.get("reason"),
        "enrichment": enrichment_sources(layer),
        "flags": {
            "elite_core": ELITE_CORE_ON,
            "cross_league_enrichment": CROSS_LEAGUE_ENRICHMENT,
            "cross_league_market": CROSS_LEAGUE_MARKET,
            "fiba_isolated": FIBA_ISOLATED_MODE,
            "market_test_mode": MARKET_TEST_MODE,
        }
    }
