# -*- coding: utf-8 -*-
"""
FAZ-17 Market Utilities
- implied probability
- model + market harmony (edge)
- coupon candidate filtering (edge picker)

Bu dosya SADECE matematik/filtreleme katmanıdır.
Provider fetch işi (Odds API vs) başka modülde olmalı.
"""

from __future__ import annotations

from typing import Any, Dict, List


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
    model_prob_under: float | None,
    odds_over: float,
    odds_under: float,
) -> Dict[str, float]:
    """
    Model tahmini + piyasa oranlarını birleştirir:

    Dönen alanlar:
    - implied_over / implied_under
    - model_prob_over / model_prob_under
    - edge_over / edge_under   (model - implied)
    """
    mpo = _clamp01(model_prob_over)

    # model_prob_under verilmediyse tamamlayıcı kullan
    if model_prob_under is None:
        mpu = 1.0 - mpo
    else:
        mpu = _clamp01(model_prob_under)

    imp_over = implied_prob(odds_over)
    imp_under = implied_prob(odds_under)

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


def faz17_pick_edge_lines(
    candidates: List[Dict[str, Any]],
    min_edge: float = 0.03,
) -> List[Dict[str, Any]]:
    """
    Kupon adaylarını edge'e göre filtreler.

    Beklenen candidate alanları:
    - model_prob_over (zorunlu)
    - model_prob_under (opsiyonel)
    - odds_over (zorunlu)
    - odds_under (zorunlu)

    min_edge: 0.03 -> %3 edge eşiği
    """
    out: List[Dict[str, Any]] = []
    thr = float(min_edge)

    for c in candidates or []:
        try:
            mpo = float(c.get("model_prob_over", 0.0))
            mpu_raw = c.get("model_prob_under", None)
            mpu = None if mpu_raw is None else float(mpu_raw)

            oo = float(c.get("odds_over", 0.0))
            ou = float(c.get("odds_under", 0.0))

            market_info = faz17_enrich_with_market(
                model_prob_over=mpo,
                model_prob_under=mpu,
                odds_over=oo,
                odds_under=ou,
            )

            best_edge = max(market_info["edge_over"], market_info["edge_under"])
            if best_edge >= thr:
                merged = dict(c)
                merged.update(market_info)
                merged["best_edge"] = float(best_edge)
                out.append(merged)

        except Exception:
            # Tek aday patladı diye tüm liste çökmemeli
            continue

    # Büyük edge en üstte
    out.sort(key=lambda x: float(x.get("best_edge", 0.0)), reverse=True)
    return out


__all__ = [
    "implied_prob",
    "faz17_enrich_with_market",
    "faz17_pick_edge_lines",
]
