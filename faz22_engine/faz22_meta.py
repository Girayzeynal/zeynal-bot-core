from typing import Dict, Any
from faz23_engine.faz23_state import faz23_get_league_calibration


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def faz22_meta_engine(match_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    KURAL:
    - base_pred ASLA marketten gelmez
    - market SADECE confidence / risk etkiler
    """

    league = match_data["league"]
    base = float(match_data["base_pred"])
    band = match_data["band"]
    market = match_data.get("market", {})

    line = market.get("line")
    delta = None
    if line is not None:
        delta = round(line - base, 1)

    confidence = float(match_data.get("confidence", 0.9))
    if delta is not None:
        confidence -= min(0.15, abs(delta) * 0.02)

    cal = faz23_get_league_calibration(league)
    base += cal.get("bias_total", 0.0)
    confidence = _clamp(confidence * cal.get("conf_scale", 1.0), 0.35, 0.97)

    risk = "LOW"
    if delta is not None and abs(delta) >= 8:
        risk = "HIGH"
    elif delta is not None and abs(delta) >= 4:
        risk = "MID"

    return {
        "league": league,
        "base_pred": round(base, 1),
        "band": band,
        "confidence": round(confidence, 2),
        "risk": risk,
        "market": {
            "line": line,
            "delta": delta,
            "provider": market.get("provider"),
            "used": market.get("used"),
        },
    } 
