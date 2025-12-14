# -*- coding: utf-8 -*-
"""
FAZ-17 Market Adjust Module

Amaç:
- FAZ-13 simülasyon çıktısını
- FAZ-17 market edge bilgisi ile
- kontrollü şekilde ayarlamak
"""

from __future__ import annotations

from typing import Dict


def faz17_market_adjust(
    simulation_result: Dict[str, float],
    market_edge: Dict[str, float],
    weight: float = 0.5,
) -> Dict[str, float]:
    """
    FAZ-13 simülasyon çıktısını market edge ile yumuşak şekilde ayarlar.

    simulation_result örnek:
    {
        "predicted_total": 184.5,
        "confidence": 0.62
    }

    market_edge örnek:
    {
        "pick": "OVER" | "UNDER",
        "confidence": 0.08
    }
    """

    adjusted = dict(simulation_result)

    pick = market_edge.get("pick")
    edge_conf = float(market_edge.get("confidence", 0.0))

    if not pick or edge_conf <= 0:
        return adjusted

    # confidence boost (sınırlı)
    base_conf = float(adjusted.get("confidence", 0.5))
    boost = min(edge_conf * weight, 0.15)

    adjusted["confidence"] = max(
        0.0,
        min(1.0, base_conf + boost),
    )

    # yön bilgisi ekle (FAZ-13 debug için)
    adjusted["market_adjust"] = {
        "pick": pick,
        "edge_confidence": edge_conf,
        "applied_weight": weight,
    }

    return adjusted
