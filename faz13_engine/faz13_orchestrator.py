from __future__ import annotations
import math
from typing import Dict, Any, Optional

LEAGUE_PROFILE = {
    "NBA": {"band_half": 6.0, "weights": [0.24, 0.25, 0.25, 0.26]},
    "DEFAULT": {"band_half": 6.0, "weights": [0.25, 0.25, 0.25, 0.25]},
}


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _round_half(x: float) -> float:
    return round(x * 2.0) / 2.0


def _split_periods(total: float, w):
    q1 = round(total * w[0])
    q2 = round(total * w[1])
    q3 = round(total * w[2])
    q4 = round(total * w[3])
    return {"q1": q1, "q2": q2, "h1": q1 + q2, "q3": q3, "q4": q4, "h2": q3 + q4}


def run_faz13_auto_pipeline(
    *,
    league: str,
    home: str,
    away: str,
    date_str: str,
    market_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    profile = LEAGUE_PROFILE.get(league.upper(), LEAGUE_PROFILE["DEFAULT"])

    # TEAM BASELINE (ASLA MARKET DEĞİL)
    base_pred = 222.0 if league.upper() == "NBA" else 160.0
    base_pred = _round_half(base_pred)

    band_half = profile["band_half"]
    band = [int(base_pred - band_half), int(base_pred + band_half)]
    periods = _split_periods(base_pred, profile["weights"])

    market = market_data or {}
    line = market.get("totals_line")
    delta = None
    if line is not None:
        delta = round(line - base_pred, 1)

    confidence = 0.92
    if delta is not None:
        confidence -= min(0.12, abs(delta) * 0.02)
    confidence = _clamp(confidence, 0.35, 0.97)

    risk = "LOW"

    return {
        "match": {"league": league, "date": date_str, "home": home, "away": away},
        "base_pred": base_pred,
        "band": band,
        "periods": periods,
        "confidence": round(confidence, 2),
        "risk": risk,
        "market": {
            "line": line,
            "delta": delta,
            "provider": market.get("provider"),
            "used": market.get("used", False),
        },
    } 
