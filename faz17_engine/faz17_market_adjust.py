# -*- coding: utf-8 -*-
"""
FAZ-17 Market Adjust Layer (Final)

Bu dosyanın asıl görevi:
- FAZ-13 simülasyon çıktısını market edge ile yumuşak şekilde ayarlamak.

Geriye uyumluluk (legacy):
- Bazı eski importlar yanlışlıkla bu dosyadan core fonksiyonları isteyebilir.
  Bu durumda çökmesin diye faz17_market.py içindeki doğru fonksiyonlara proxy eder.
"""

from __future__ import annotations

from typing import Dict, Optional

# ✅ Doğru yerden core fonksiyonları al (proxy / backward compat)
from .faz17_market import (  # noqa: F401
    implied_prob,
    faz17_enrich_with_market,
    faz17_pick_edge_lines,
)


def faz17_market_adjust(
    simulation_result: Dict[str, float],
    market_pick: Dict[str, float],
    weight: float = 0.5,
    max_boost: float = 0.12,
) -> Dict[str, float]:
    """
    Market edge bilgisini FAZ-13 çıktısına YUMUŞAK şekilde uygular.

    simulation_result örnek:
    {
        "predicted_total": 184.5,
        "confidence": 0.62
    }

    market_pick örnek:
    {
        "pick": "OVER" | "UNDER" | None,
        "confidence": 0.08
    }

    weight: market etkisi (0..1)
    max_boost: confidence artış limiti (modeli domine etmesin)
    """

    adjusted = dict(simulation_result)

    pick: Optional[str] = market_pick.get("pick")
    try:
        edge_conf = float(market_pick.get("confidence", 0.0))
    except Exception:
        edge_conf = 0.0

    if not pick or edge_conf <= 0:
        return adjusted

    try:
        base_conf = float(adjusted.get("confidence", 0.5))
    except Exception:
        base_conf = 0.5

    # Market ASLA modeli domine etmez
    boost = min(edge_conf * float(weight), float(max_boost))

    new_conf = base_conf + boost
    if new_conf < 0.0:
        new_conf = 0.0
    if new_conf > 1.0:
        new_conf = 1.0

    adjusted["confidence"] = float(new_conf)

    # Debug/meta
    adjusted["market_adjust"] = {
        "pick": pick,
        "edge_confidence": float(edge_conf),
        "weight": float(weight),
        "max_boost": float(max_boost),
    }

    return adjusted


__all__ = [
    # core proxies (legacy-safe)
    "implied_prob",
    "faz17_enrich_with_market",
    "faz17_pick_edge_lines",
    # actual adjust
    "faz17_market_adjust",
]
