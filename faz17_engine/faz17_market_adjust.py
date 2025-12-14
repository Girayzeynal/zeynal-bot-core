# -*- coding: utf-8 -*-
"""
FAZ-17 Market Core
- implied probability
- model + market harmony
- edge detection
"""

from __future__ import annotations

from typing import Dict


# ================================================================
# 🔢 IMPLIED PROBABILITY
# ================================================================
def implied_prob(odds: float) -> float:
    """
    Decimal odds -> implied probability
    Örn: 1.80 -> 0.555...
    """
    try:
        o = float(odds)
        if o <= 1.0:
            return 0.0
        return 1.0 / o
    except Exception:
        return 0.0


# ================================================================
# 🧠 MODEL + MARKET HARMONY
# ================================================================
def faz17_enrich_with_market(
    model_prob_over: float,
    model_prob_under: float,
    odds_over: float,
    odds_under: float,
) -> Dict[str, float]:
    """
    Model tahmini + piyasa oranlarını alır:
    - implied_over / implied_under
    - model_edge_over / model_edge_under
    döndürür.
    """

    imp_over = implied_prob(odds_over)
    imp_under = implied_prob(odds_under)

    # model probability normalize
    try:
        mpo = float(model_prob_over)
    except Exception:
        mpo = 0.5

    try:
        mpu = float(model_prob_under)
    except Exception:
        mpu = 0.0

    if mpu <= 0.0:
        mpu = max(0.0, min(1.0, 1.0 - mpo))
    else:
        mpu = max(0.0, min(1.0, mpu))

    mpo = max(0.0, min(1.0, mpo))

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


# ================================================================
# 🎯 EDGE LINE PICKER
# ================================================================
def faz17_pick_edge_lines(
    enriched_market: Dict[str, float],
    threshold: float = 0.03,
) -> Dict[str, float]:
    """
    Edge threshold üstündeki tarafı seçer.
    FAZ-13 ve FAZ-17 adjust tarafından okunur.
    """

    edge_over = enriched_market.get("edge_over", 0.0)
    edge_under = enriched_market.get("edge_under", 0.0)

    pick = None
    confidence = 0.0

    if edge_over > threshold and edge_over > edge_under:
        pick = "OVER"
        confidence = edge_over
    elif edge_under > threshold and edge_under > edge_over:
        pick = "UNDER"
        confidence = edge_under

    return {
        "pick": pick,
        "confidence": float(confidence),
        "edge_over": float(edge_over),
        "edge_under": float(edge_under),
    }
