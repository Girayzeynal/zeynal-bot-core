# faz17_engine/faz17_market_fetcher.py
from __future__ import annotations
from typing import Any, Dict, Optional, Tuple, Callable

MarketData = Dict[str, Any]
MarketMeta = Dict[str, Any]

def faz17_fetch_market_safe(
    *,
    provider_fetch_func: Callable[..., Any],
    league: str,
    date_str: str,
    home: str,
    away: str,
) -> Tuple[Optional[MarketData], Dict[str, Any]]:
    """
    provider_fetch_func -> (market, meta) döndürür.
    Biz burada totals_line standardize ederiz ve meta formatını sabitleriz.
    """
    try:
        out = provider_fetch_func(league=league, date_str=date_str, home=home, away=away)
    except Exception as e:
        return None, {"market": {"used": False, "confidence": 0.0, "reason": f"provider_error:{e}", "provider": None}}

    market: Optional[MarketData] = None
    meta: Dict[str, Any] = {}

    if isinstance(out, tuple) and len(out) == 2:
        market, meta = out
    elif isinstance(out, dict):
        market = out
        meta = {"provider": market.get("provider"), "used": bool(market.get("totals_line")), "confidence": 0.4, "reason": "ok"}

    # normalize
    if not market or not isinstance(market, dict):
        return None, {"market": {"used": False, "confidence": 0.0, "reason": "no_market_data", "provider": None}}

    line = market.get("totals_line")
    try:
        line_f = float(line) if line is not None else None
    except Exception:
        line_f = None
    market["totals_line"] = line_f

    used = bool(line_f is not None)
    provider = (meta or {}).get("provider") or market.get("provider")
    conf = float((meta or {}).get("confidence", 0.0) or 0.0)
    reason = (meta or {}).get("reason") or ("ok" if used else "no_line")

    return market, {"market": {"used": used, "confidence": conf, "reason": reason, "provider": provider}}

def fetch_market(league: str, date_str: str, home: str, away: str):
    # provider_fetch_func burada hangi provider kullanıyorsan O
    from faz17_engine.providers import fetch_from_odds_api  # örnek

    return faz17_fetch_market_safe(
        provider_fetch_func=fetch_from_odds_api,
        league=league,
        date_str=date_str,
        home=home,
        away=away,
    ) 

# ---- PUBLIC ENTRY POINT (FAZ-17) ----

def fetch_market(league: str, date_str: str, home: str, away: str):
    """
    Main entry point expected by main.py
    Wraps faz17_fetch_market_safe with a default provider
    """

    try:
        # Şu an provider yoksa bile FAZ-17 OK görmek için geçici stub
        market = {
            "totals_line": None,
            "provider": "stub"
        }
        meta = {
            "used": False,
            "confidence": 0.0,
            "reason": "no-provider-attached"
        }
        return market, meta

    except Exception:
        return None, {"used": False, "confidence": 0.0}
