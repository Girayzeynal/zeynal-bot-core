# -*- coding: utf-8 -*-
"""
FAZ-17 Engine – Public Interface

Bu dosya SADECE paket yüzeyini tanımlar.
İmplementasyon import etmez.
Yan etki yaratmaz.
"""

from typing import Callable, Dict, Any, Tuple, Optional

# === PUBLIC CONTRACT ===

MarketResult = Optional[Dict[str, Any]]
MarketMeta = Dict[str, Any]

FetchMarketFunc = Callable[..., Tuple[MarketResult, MarketMeta]]

# === EXPORT NAME (late binding) ===
# main.py bu ismi import eder, implementasyonu içeride çözer

faz17_fetch_market_safe: FetchMarketFunc
