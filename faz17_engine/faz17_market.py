# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, Optional


def _clamp01(x: Any) -> float:
    try:
        v = float(x)
    except Exception:
        return 0.0
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def implied_prob(decimal_odds: Any) -> float:
    """
    Decimal odds -> implied probability.
    1.80 -> 0.555...
    """
    try:
        o = float(decimal_odds)
        if o <= 1.0:
            return 0.0
        return 1.0 / o
    except Exception:
        return 0.0


def faz17_enrich_with_market(
    *,
    model_prob_over: Any,
    model_prob_under: Optional[Any],
    over_odds: Any,
    under_odds: Any,
) -> Dict[str, float]:
    """
    Model + Market edge.
    """
    mpo = _clamp01(model_prob_over)
    if model_prob_under is None:
        mpu = _clamp01(1.0 - mpo)
    else:
        mpu = _clamp01(model_prob_under)

    imp_over = implied_prob(over_odds)
    imp_under = implied_prob(under_odds)

    edge_over = float(mpo - imp_over)
    edge_under = float(mpu - imp_under)

    return {
        "implied_over": float(imp_over),
        "implied_under": float(imp_under),
        "model_prob_over": float(mpo),
        "model_prob_under": float(mpu),
        "edge_over": float(edge_over),
        "edge_under": float(edge_under),
    }
