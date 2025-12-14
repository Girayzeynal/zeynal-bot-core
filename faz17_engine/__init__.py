# -*- coding: utf-8 -*-
"""
FAZ-17 Engine package exports.

Bu modül:
 - Market odds hesap/edge fonksiyonları
 - Market fetcher (dış kaynaklardan total line çekme)
 - Market adjust ve safe fetch için stabil import yüzeyi sağlar.
"""

from __future__ import annotations

# Faz17 core functions
from .faz17_market import (
    implied_prob,
    faz17_enrich_with_market,
    faz17_pick_edge_lines,
)

from .faz17_market_adjust import (
    faz17_market_adjust,
)

# 🎯 Safe fetch wrapper
from .faz17_market_fetcher import (
    faz17_fetch_market_safe,
)

# Backward compatibility alias (opsiyonel ama önerilir)
# Eğer eski kodlar hala 'faz17_fetch_market' beklerse bunu kullanır:
faz17_fetch_market = faz17_fetch_market_safe

__all__ = [
    "implied_prob",
    "faz17_enrich_with_market",
    "faz17_pick_edge_lines",
    "faz17_market_adjust",
    "faz17_fetch_market_safe",
    "faz17_fetch_market",  # alias
]
