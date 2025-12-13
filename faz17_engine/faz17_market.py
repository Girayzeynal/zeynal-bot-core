# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, List


# -------------------------------------------------------
# IMPLIED PROBABILITY
# -------------------------------------------------------
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


# -------------------------------------------------------
# MODEL + MARKET HARMONY
# -------------------------------------------------------
def faz17_enrich_with_market(
    model_prob_over: float,
    model_prob_under: float,
    odds_over: float,
    odds_under: float,
) -> Dict[str, float]:
    """
    Model tahmini + piyasa oranlarını alıp:
      - implied_over / implied_under
      - model_edge_over / model_edge_under
    döndürür.
    """
    imp_over = implied_prob(odds_over)
    imp_under = implied_prob(odds_under)

    # Under attaching: eğer model_under yoksa tamamlayıcı yap
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


# -------------------------------------------------------
# Kupon için EDGE SEÇİM MOTORU
# -------------------------------------------------------
def faz17_pick_edge_lines(
    candidates: List[Dict[str, Any]],
    min_edge: float = 0.03,
) -> List[Dict[str, Any]]:
    """
    Kupon aday listesini alır, minimum edge'e göre filtreler.
    candidates elemanı örn:
      {
        "model_prob_over": 0.56,
        "odds_over": 1.90,
        "odds_under": 1.90,
        ... diğer alanlar ...
      }
    """
    selected: List[Dict[str, Any]] = []

    for c in candidates or []:
        try:
            market_info = faz17_enrich_with_market(
                model_prob_over=float(c.get("model_prob_over", 0.5)),
                model_prob_under=float(c.get("model_prob_under", 0.0)),
                odds_over=float(c.get("odds_over", 0.0)),
                odds_under=float(c.get("odds_under", 0.0)),
            )
            best_edge = max(market_info["edge_over"], market_info["edge_under"])
            if best_edge >= float(min_edge):
                out = dict(c)
                out.update(market_info)
                selected.append(out)
        except Exception:
            # tek aday patladı diye tüm listeyi yakma
            continue

    return selected
