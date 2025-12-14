# ================================================================
# 🎯 FAZ-17 MARKET FETCHER (ELITE CORE SAFE)
# ================================================================

import logging
from typing import Tuple, Optional, Any
from datetime import datetime, timezone, timedelta
import re

log = logging.getLogger(__name__)

# ================================================================
# 🧠 ELITE CORE IMPORTS (SINGLE SOURCE OF TRUTH)
# ================================================================
from core.elite_league_registry import (
    normalize_league_input,
    resolve_league_layer,
    market_permission,
    enrichment_sources,
    ELITE_CORE_ON,
)

# ================================================================
# 🧼 TEAM NORMALIZATION
# ================================================================
def _slug_team(name: str) -> str:
    if not name:
        return ""
    s = name.lower().strip()
    s = s.replace("ı", "i").replace("İ", "i")
    s = s.replace("ş", "s").replace("ğ", "g").replace("ç", "c")
    s = s.replace("ö", "o").replace("ü", "u")
    for w in ["bc", "b.c.", "basketball", "beko", "sk", "spor kulubu", "club"]:
        s = s.replace(w, " ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _parse_date_tr(date_str: str) -> datetime:
    # YYYY-MM-DD → Istanbul time (UTC+3)
    dt = datetime.strptime(date_str.strip(), "%Y-%m-%d")
    return dt.replace(tzinfo=timezone(timedelta(hours=3)))

# ================================================================
# 🔒 HARD EVENT MATCH (ANTI-WRONG-MATCH)
# ================================================================
def hard_match_event(event: dict, home: str, away: str, date_str: str) -> bool:
    try:
        eh = _slug_team(event.get("home_team", ""))
        ea = _slug_team(event.get("away_team", ""))
        th = _slug_team(home)
        ta = _slug_team(away)

        # strict team match
        if not (eh == th and ea == ta):
            return False

        ct_raw = event.get("commence_time") or event.get("commenceTime")
        if not ct_raw:
            return False

        ct_raw = ct_raw.replace("Z", "+00:00")
        ct = datetime.fromisoformat(ct_raw)
        if ct.tzinfo is None:
            ct = ct.replace(tzinfo=timezone.utc)

        ct_local = ct.astimezone(timezone(timedelta(hours=3)))
        target = _parse_date_tr(date_str)

        # same day OR ±12h tolerance
        if target.date() == ct_local.date():
            return True

        if abs((ct_local - target).total_seconds()) <= 12 * 3600:
            return True

        return False
    except Exception:
        return False

# ================================================================
# 🚦 SAFE MARKET FETCH WRAPPER
# ================================================================
def faz17_fetch_market_safe(
    provider_fetch_func,
    league: str,
    date_str: str,
    home: str,
    away: str,
) -> Tuple[Optional[Any], dict]:
    """
    Wrapper that enforces Elite Core rules + hard event matching.
    Returns: (market_data | None, market_meta)
    """

    league_code = normalize_league_input(league)
    layer = resolve_league_layer(league_code)
    perm = market_permission(layer)

    market_meta = {
        "primary_league": league_code,
        "league_layer": layer,
        "enrichment": enrichment_sources(layer),
        "market": {
            "used": False,
            "confidence": None,
            "reason": None,
        },
    }

    if not ELITE_CORE_ON:
        market_meta["market"]["reason"] = "ELITE_CORE_DISABLED"
        return None, market_meta

    if not perm.get("allowed"):
        market_meta["market"]["reason"] = perm.get("reason", "NOT_ALLOWED")
        return None, market_meta

    # ------------------------------------------------------------
    # Provider fetch
    # ------------------------------------------------------------
    try:
        raw = provider_fetch_func(
            league=league_code,
            date_str=date_str,
            home=home,
            away=away,
        )
    except Exception as e:
        market_meta["market"]["reason"] = f"FETCH_FAIL: {e}"
        log.warning(f"FAZ-17 provider fetch failed: {e}")
        return None, market_meta

    # ------------------------------------------------------------
    # Case 1: single event dict
    # ------------------------------------------------------------
    if isinstance(raw, dict):
        if hard_match_event(raw, home, away, date_str):
            market_meta["market"]["used"] = True
            market_meta["market"]["confidence"] = perm.get("confidence")
            return raw, market_meta

        market_meta["market"]["reason"] = "NO_PRIMARY_EVENT_MATCH"
        return None, market_meta

    # ------------------------------------------------------------
    # Case 2: list of events
    # ------------------------------------------------------------
    if isinstance(raw, list):
        for ev in raw:
            if isinstance(ev, dict) and hard_match_event(ev, home, away, date_str):
                market_meta["market"]["used"] = True
                market_meta["market"]["confidence"] = perm.get("confidence")
                return ev, market_meta

        market_meta["market"]["reason"] = "NO_PRIMARY_EVENT_MATCH"
        return None, market_meta

    # ------------------------------------------------------------
    # Unknown provider shape
    # ------------------------------------------------------------
    market_meta["market"]["reason"] = "UNKNOWN_PROVIDER_SHAPE"
    return None, market_meta
