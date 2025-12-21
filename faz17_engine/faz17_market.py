# faz17_engine/faz17_market.py
"""
FAZ-17 MARKET ANALYSIS MODULE

- FINAL ARCHITECTURE ile UYUMLU
- Karar üretmez
- Sadece market ile model farkını ANALİZ eder
- Debug / analiz / UI katmanında kullanılabilir
"""

from typing import Dict, Optional


def analyze_market_delta(
    model_total: Optional[float],
    market_line: Optional[float],
) -> Dict[str, Optional[float]]:
    """
    Model tahmini ile market arasındaki farkı hesaplar.
    Pipeline'da KULLANILMAZ, sadece ANALİZ amaçlıdır.
    """
    if model_total is None or market_line is None:
        return {
            "used": False,
            "delta": None,
            "direction": None,
        }

    delta = market_line - model_total

    if delta > 0:
        direction = "MARKET_OVER_MODEL"
    elif delta < 0:
        direction = "MODEL_OVER_MARKET"
    else:
        direction = "EQUAL"

    return {
        "used": True,
        "delta": round(delta, 2),
        "direction": direction,
    }


__all__ = ["analyze_market_delta"]
