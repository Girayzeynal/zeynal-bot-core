# -*- coding: utf-8 -*-
"""
FAZ-17 package surface.

Amaç:
- Dışarıdan tek, stabil giriş: faz17_fetch_market_safe
- providers.py var/yok fark etmeden çalışabilsin (fallback içeride)
"""

from .faz17_market_fetcher import faz17_fetch_market_safe  # noqa: F401
