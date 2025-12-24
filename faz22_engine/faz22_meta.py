# faz22_engine/faz22_meta.py

from __future__ import annotations
import time
from typing import Dict, Any

from faz23_engine.faz23_state import faz23_get_league_calibration


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def faz22_meta_engine(match_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    FAZ-22 Meta Engine
    - FAZ-13 base prediction
    - FAZ-17 market influence
    - Confidence & band calibration
    - FAZ-23 learning correction (online)
    """

    ts = int(time.time())

    league = str(match_data.get("league", "UNKNOWN")).upper()
    base_pred = float(match_data.get("base_pred", match_data.get("faz13_pred", 0.0)))
    band = match_data.get("band")
    market_line = match_data.get("market", {}).get("line")

    # --- Market parsing ---
    try:
        market_line_f = float(market_line) if market_line is not None else None
    except Exception:
        market_line_f = None

    # --- Market weight (small influence) ---
    w_market = 0.10 if market_line_f is not None else 0.0
    w_base = 1.0 - w_market

    meta_pred = base_pred
    if market_line_f is not None:
        meta_pred = (base_pred * w_base) + (market_line_f * w_market)

    # --- Variance from band ---
    var = 6.0
    if isinstance(band, (list, tuple)) and len(band) == 2:
        try:
            var = max(3.0, (float(band[1]) - float(band[0])))
        except Exception:
            var = 6.0

    low = round(meta_pred - var)
    high = round(meta_pred + var)

    # --- Market delta ---
    delta = None
    if market_line_f is not None:
        delta = round(market_line_f - base_pred, 1)

    # --- Base confidence from variance ---
    var_conf = _clamp(1.0 - (var / 100.0), 0.35, 0.97)

    # --- League-based penalty ---
    penalty = 0.0
    if delta is not None:
        ad = abs(delta)
        if league == "NBA":
            if ad >= 8:
                penalty = 0.12
            elif ad >= 5:
                penalty = 0.07
        elif league == "EUROLEAGUE":
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

    # =====================================================================
    # 🔥 FAZ-23 LEARNING CALIBRATION (ONLINE / RAM-BASED)
    # =====================================================================
    cal = faz23_get_league_calibration(league)
    bias = float(cal.get("bias_total", 0.0))

    # base_pred + band shift
    meta_pred = meta_pred + bias
    low = int(low + bias)
    high = int(high + bias)

    # confidence calibration
    conf = confidence
    conf = conf * float(cal.get("conf_scale", 1.0)) + float(cal.get("conf_bias", 0.0))
    confidence = _clamp(conf, 0.0, 1.0)

    # =====================================================================
    # FINAL OUTPUT
    # =====================================================================
    return {
        "ts": ts,
        "engine": "FAZ-22",
        "league": league,
        "base_pred": round(meta_pred, 1),
        "band": [low, high],
        "confidence": round(confidence, 3),
        "risk": "LOW" if confidence >= 0.85 else "MID" if confidence >= 0.65 else "HIGH",
        "market": {
            "line": market_line_f,
            "delta": delta,
            "w_market": w_market,
            "penalty": penalty,
        },
    } 
