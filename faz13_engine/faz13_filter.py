from typing import Any, Dict, List

def faz13_oynanmaz_filter(faz13_result: Dict[str, Any]) -> Dict[str, Any]:
    band = faz13_result.get("band", [])
    market = faz13_result.get("market", {}) if isinstance(faz13_result.get("market"), dict) else {}
    used = bool(market.get("used", False))
    mconf = float(market.get("confidence", 0.0) or 0.0)

    risk = "MID"
    play = True
    reason = "ok"
    tags: List[str] = []

    width = None
    if isinstance(band, list) and len(band) == 2:
        try:
            width = float(band[1]) - float(band[0])
        except Exception:
            width = None

    if width is not None and width >= 18:
        play = False
        risk = "HIGH"
        reason = "band_too_wide"
        tags.append("OYNANMAZ_BAND_WIDE")

    if play and width is not None and width >= 14 and (not used or mconf <= 0.35):
        play = False
        risk = "HIGH"
        reason = "weak_market_and_wide_band"
        tags.append("OYNANMAZ_WEAK_MARKET")

    if play and used and mconf >= 0.75 and width is not None and width <= 14:
        risk = "LOW"
        tags.append("MARKET_SUPPORTS_STABILITY")

    return {"play": play, "risk": risk, "reason": reason, "tags": tags}
