# -*- coding: utf-8 -*-
"""
FAZ-17 Engine – Public Export Surface

Bu dosya SADECE gerçekten var olan
ve aktif kullanılan fonksiyonları dışarı açar.
"""

from __future__ import annotations

# =================================================
# Market core (faz17_market.py)
# =================================================
from .faz17_market import (
    implied_prob,
    faz17_enrich_with_market,
    faz17_pick_edge_lines,
)

# =================================================
# Market fetcher (SAFE)
# =================================================
from .faz17_market_fetcher import (
    faz17_fetch_market_safe,
)

# Geriye uyumluluk (legacy)
faz17_fetch_market = faz17_fetch_market_safe

# =================================================
# Market adjust (faz17_market_adjust.py)
# =================================================
from .faz17_market_adjust import (
    faz17_market_adjust,
)

# =================================================
# Public API
# =================================================
__all__ = [
    # market core
    "implied_prob",
    "faz17_enrich_with_market",
    "faz17_pick_edge_lines",

    # market fetch
    "faz17_fetch_market_safe",
    "faz17_fetch_market",

    # market adjust
    "faz17_market_adjust",
]
