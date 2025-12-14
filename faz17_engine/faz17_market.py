# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, Optional


def implied_prob(odds: float) -> float:
    """
    Decimal odd -> implied probability.
    Örn: 1.80 -> 0.555...
    """
    try:
        o = float(odds)
        if o <= 1.0:
            return 0.0
        return 1.0 / o
    except Exception:
        return 0.0


def _clamp01(x: float) -> float:
    try:
        v = float(x)
    except Exception:
        v = 0.0
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def faz17_enrich_with_market(
    model_prob_over: float,
    model_prob_under: Optional[float],
    odds_over: float,
    odds_under: float,
) -> Dict[str, float]:
    """
    Model tahmini + piyasa oranlarını birleştirir.
    Dönen alanlar:
      - implied_over / implied_under
      - model_prob_over / model_prob_under
      - edge_over / edge_under   (model - implied)
    """
    imp_over = implied_prob(odds_over)
    imp_under = implied_prob(odds_under)

    mpo = _clamp01(model_prob_over)

    # model_prob_under verilmediyse tamamlayıcı kullan
    if model_prob_under is None:
        mpu = _clamp01(1.0 - mpo)
    else:
        mpu = _clamp01(model_prob_under)

    edge_over = mpo - imp_over
    edge_under = mpu - imp_under

    return {
        "implied_over": float(imp_over),
        "implied_under": float(imp_under),
        "model_prob_over": float(mpo),
        "model_prob_under": float(mpu),
        "edge_over": float(edge_over),
        "edge_under": float(edge_under),
    }
