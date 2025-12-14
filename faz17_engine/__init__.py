# -*- coding: utf-8 -*-
"""
FAZ-17 package surface.

Amaç:
- Dışarıdan tek ve stabil giriş:
  - faz17_fetch_market_safe
  - faz17_fetch_market

Not:
- providers.py varsa onu kullanır (daha güncel).
- Yoksa faz17_market_fetcher fallback'ine döner (legacy).
"""

from __future__ import annotations

# Önce providers (senin istediğin yer)
try:
    from .providers import faz17_fetch_market_safe, faz17_fetch_market  # noqa: F401
except Exception:
    # providers yoksa / bozuksa legacy fetcher'dan en azından safe fonksiyonu çıkar
    from .faz17_market_fetcher import faz17_fetch_market_safe  # type: ignore # noqa: F401

    def faz17_fetch_market(*args, **kwargs):  # type: ignore
        raise RuntimeError("FAZ-17 providers.py bulunamadı veya import edilemedi (faz17_fetch_market yok).")


__all__ = [
    "faz17_fetch_market_safe",
    "faz17_fetch_market",
] 
