# faz22_engine/faz22_meta.py
from __future__ import annotations
import time
from typing import Dict, Any

def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def faz22_meta_engine(match_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Meta: base + (small) market influence + confidence calibration seed.
    Lig bazlı politika:
      - NBA: market şişme büyükse risk artar / oynanmaz filtresini tetikleyebilir
      - EUROLEAGUE: şişme varsa confidence düşer, ama oynanmaz agresif değil
      - Others: orta yol
    """
    ts = int(time.time())

    league = str(match_data.get("league", "UNKNOWN")).upper()
    base_pred = float(match_data.get("faz13_pred", match_data.get("base_pred", 0.0)) or 0.0)
    band = match_data.get("band") or [None, None]
    market_line = match_data.get("faz17_market_ref", None)

    try:
        market_line_f = float(market_line) if market_line is not None else None
    except Exception:
        market_line_f = None

    # very small influence
    w_market = 0.10 if market_line_f is not None else 0.0
    w_base = 1.0 - w_market

    meta_pred = base_pred
    if market_line_f is not None:
        meta_pred = (base_pred * w_base) + (market_line_f * w_market)

    # variance from band
    var = 6.0
    if isinstance(band, (list, tuple)) and len(band) == 2:
        try:
            var = max(3.0, (float(band[1]) - float(band[0])) / 2.0)
        except Exception:
            var = 6.0

    low = round(meta_pred - var)
    high = round(meta_pred + var)

    # market delta
    delta = None
    if market_line_f is not None:
        delta = round(market_line_f - base_pred, 1)

    # base confidence from variance
    var_conf = _clamp(1.0 - (var / 100.0), 0.35, 0.97)

    # lig bazlı penalty
    penalty = 0.0
    if delta is not None:
        ad = abs(delta)
        if league == "NBA":
            # NBA: büyük şişme sert
            if ad >= 8:
                penalty = 0.12
            elif ad >= 5:
                penalty = 0.07
        elif league == "EUROLEAGUE":
            # EL: daha yumuşak
            if ad >= 7:
                penalty = 0.08
            elif ad >= 4:
                penalty = 0.04
        else:
            if ad >= 7:
                penalty = 0.10
            elif ad >= 4:
                penalty = 0.05

    confidence = _clamp(var_conf - penalty, 0.35, 0.97)

    return {
        "ts": ts,
        "engine": "FAZ-22",
        "league": league,
        "meta_pred": round(meta_pred, 1),
        "range_low": int(low),
        "range_high": int(high),
        "confidence": round(confidence, 3),
        "market": {
            "line": market_line_f,
            "delta": delta,
            "w_market": w_market,
            "penalty": penalty,
        }
    } 
