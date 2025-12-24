from __future__ import annotations
from typing import Dict, Any
from faz23_engine.faz23_state import faz23_get_league_calibration

def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def faz22_meta_engine(match_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    KURAL: BASE SADECE TEAM BASELINE'DAN GELİR.
    Market sadece confidence/risk kırpma içindir.
    ÇIKTI CONTRACT:
      - base_pred
      - band
      - market: {line, delta, provider, used}
      - confidence
      - risk
    """

    league = str(match_data.get("league", "UNKNOWN")).upper()

    # ✅ base_pred tek kaynak
    base_pred = float(match_data.get("base_pred", 0.0))
    band = match_data.get("band") or [int(base_pred - 12), int(base_pred + 12)]

    market = match_data.get("market") or {}
    line = market.get("line", None)

    # market delta sadece kıyas
    delta = None
    if line is not None:
        try:
            line_f = float(line)
            delta = round(line_f - base_pred, 1)
            line = line_f
        except Exception:
            line = None
            delta = None

    # confidence: FAZ-13’ten gelir, market sapması kırpar
    confidence = float(match_data.get("confidence", 0.90))
    if delta is not None:
        confidence -= min(0.15, abs(delta) * 0.02)

    # ✅ FAZ-23 learning: küçük düzeltme (base’i ele geçirmez)
    cal = faz23_get_league_calibration(league)
    bias = float(cal.get("bias_total", 0.0))
    conf_scale = float(cal.get("conf_scale", 1.0))
    conf_bias = float(cal.get("conf_bias", 0.0))

    base_pred = base_pred + bias
    confidence = _clamp(confidence * conf_scale + conf_bias, 0.35, 0.97)

    # risk: delta büyürse risk artar
    risk = "LOW"
    if delta is not None and abs(delta) >= 8:
        risk = "HIGH"
    elif delta is not None and abs(delta) >= 4:
        risk = "MID"

    return {
        "league": league,
        "base_pred": round(base_pred, 1),
        "band": band,
        "confidence": round(confidence, 2),
        "risk": risk,
        "market": {
            "line": line,
            "delta": delta,
            "provider": market.get("provider"),
            "used": bool(market.get("used", False)),
        },
    }
