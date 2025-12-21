import time
from typing import Dict, Any

from .faz22_state import get_weights
from .faz22_confidence import combine_confidence
from faz23_engine.faz23_stats import get_summary

def faz22_meta_engine(match_data: Dict[str, Any]) -> Dict[str, Any]:
    ts = int(time.time())

    league = str(match_data.get("league", "UNKNOWN"))
    w = get_weights(league)
    w13 = float(w["w13"])
    w17 = float(w["w17"])

    base_pred = float(match_data.get("faz13_pred", match_data.get("base_pred", 165.0)))
    market_ref = match_data.get("faz17_market_ref", None)
    try:
        market_ref = float(market_ref) if market_ref is not None else None
    except Exception:
        market_ref = None

    if market_ref is None:
        w13_eff, w17_eff = 1.0, 0.0
    else:
        w13_eff, w17_eff = w13, w17

    denom = (w13_eff + w17_eff) if (w13_eff + w17_eff) > 0 else 1.0
    meta_pred = (base_pred * w13_eff + (market_ref or 0.0) * w17_eff) / denom

    band = match_data.get("band")
    if isinstance(band, (list, tuple)) and len(band) == 2:
        try:
            var = max(3.0, (float(band[1]) - float(band[0])) / 2.0)
        except Exception:
            var = max(3.0, abs(meta_pred) * 0.06)
    else:
        var = max(3.0, abs(meta_pred) * 0.06)

    low = round(meta_pred - var)
    high = round(meta_pred + var)

    var_conf = round(max(0.01, min(0.99, 1.0 - (var / 100.0))), 3)
    hist = get_summary(league)
    confidence = combine_confidence(var_conf, hist)

    return {
        "ts": ts,
        "engine": "FAZ-22",
        "league": league,
        "meta_pred": round(meta_pred, 1),
        "range_low": int(low),
        "range_high": int(high),
        "confidence": confidence,
        "weights": {"w13": round(w13_eff, 3), "w17": round(w17_eff, 3)},
        "history": hist,
    } 
