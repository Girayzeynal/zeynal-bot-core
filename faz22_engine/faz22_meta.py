import time
from typing import Dict, Any

def faz22_meta_engine(match_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    FAZ-22 META ENGINE (FINAL REBUILD v1)
    - Tek meta burası.
    - Ağırlıklar şimdilik sabit; dinamikleştirme FAZ-23 error-tags ile yapılacak.
    """
    ts = int(time.time())

    base_pred = float(match_data.get("faz13_pred", match_data.get("base_pred", 165.0)))
    market_ref = match_data.get("faz17_market_ref", None)

    # market_ref opsiyonel
    try:
        market_ref = float(market_ref) if market_ref is not None else None
    except Exception:
        market_ref = None

    # Basit ama kontrollü birleşim:
    w13 = 0.85
    w17 = 0.15 if market_ref is not None else 0.0
    denom = (w13 + w17) if (w13 + w17) > 0 else 1.0

    meta_pred = (base_pred * w13 + (market_ref or 0.0) * w17) / denom

    # Varyans: FAZ-13 band genişliği varsa onu temel al
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

    # confidence: şimdilik var’a bağlı; FAZ-23 ile tarihsel doğruluk bağlanacak
    confidence = round(max(0.01, min(0.99, 1.0 - (var / 100.0))), 3)

    return {
        "ts": ts,
        "engine": "FAZ-22",
        "meta_pred": round(meta_pred, 1),
        "range_low": int(low),
        "range_high": int(high),
        "confidence": confidence,
        "weights": {"w13": round(w13, 3), "w17": round(w17, 3)},
    } 
