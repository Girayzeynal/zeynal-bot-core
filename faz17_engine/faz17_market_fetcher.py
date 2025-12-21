from typing import Any, Dict, Optional, Tuple, Callable

MarketData = Dict[str, Any]
MarketMeta = Dict[str, Any]

def _reject(reason: str) -> Tuple[Optional[MarketData], MarketMeta]:
    return None, {"market": {"used": False, "confidence": 0.0, "reason": reason}}

def faz17_fetch_market_safe(
    provider_fetch_func: Callable[..., Any],
    league: str,
    date_str: str,
    home: str,
    away: str,
) -> Tuple[Optional[MarketData], MarketMeta]:
    if not callable(provider_fetch_func):
        return _reject("provider_missing")

    try:
        out = provider_fetch_func(league=league, date_str=date_str, home=home, away=away)
    except Exception as e:
        return _reject(f"provider_error:{e}")

    market_data: Optional[MarketData] = None
    meta: MarketMeta = {"market": {"used": False, "confidence": 0.0, "reason": "empty"}}

    if isinstance(out, tuple) and len(out) == 2:
        market_data, meta2 = out
        if isinstance(meta2, dict):
            meta = meta2
    elif isinstance(out, dict):
        market_data = out

    if not market_data or not isinstance(market_data, dict):
        return _reject("no_market_data")

    totals_line = market_data.get("totals_line", None)
    try:
        totals_line = float(totals_line) if totals_line is not None else None
    except Exception:
        totals_line = None
    market_data["totals_line"] = totals_line

    used = bool(totals_line is not None)
    conf = 0.55 if used else 0.0
    meta = {"market": {"used": used, "confidence": conf, "reason": "ok" if used else "no_line"}}
    return market_data, meta
