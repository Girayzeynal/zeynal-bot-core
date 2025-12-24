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
    try:
        out = provider_fetch_func(
            league=league, date_str=date_str, home=home, away=away
        )
    except Exception as e:
        return None, {
            "market": {
                "used": False,
                "confidence": 0.0,
                "reason": f"provider_error:{e}",
                "provider": None,
            }
        }

    market = None
    meta: Dict[str, Any] = {}

    if isinstance(out, tuple) and len(out) == 2:
        market, meta = out
    elif isinstance(out, dict):
        market = out
        meta = {
            "provider": market.get("provider"),
            "used": bool(market.get("totals_line")),
            "confidence": 0.4,
            "reason": "ok",
        }

    if not market or not isinstance(market, dict):
        return None, {
            "market": {
                "used": False,
                "confidence": 0.0,
                "reason": "no_market_data",
                "provider": None,
            }
        }

    line = market.get("totals_line")
    try:
        market["totals_line"] = float(line) if line is not None else None
    except Exception:
        market["totals_line"] = None

    used = market["totals_line"] is not None
    provider = meta.get("provider") or market.get("provider")

    return market, {
        "market": {
            "used": used,
            "confidence": float(meta.get("confidence", 0.0)),
            "reason": meta.get("reason", "ok" if used else "no_line"),
            "provider": provider,
        }
    }


def fetch_market(
    league: str, date_str: str, home: str, away: str
) -> Tuple[Optional[MarketData], Dict[str, Any]]:
    from faz17_engine.providers import fetch_from_odds_api, fetch_from_api_sports

    market, meta = faz17_fetch_market_safe(
        provider_fetch_func=fetch_from_odds_api,
        league=league,
        date_str=date_str,
        home=home,
        away=away,
    )
    if meta.get("market", {}).get("used"):
        return market, meta

    return faz17_fetch_market_safe(
        provider_fetch_func=fetch_from_api_sports,
        league=league,
        date_str=date_str,
        home=home,
        away=away,
    )
