# -*- coding: utf-8 -*-
"""
FAZ-17 package surface (tek, stabil giriş noktası)

Dışarıya şunları export eder:
- faz17_fetch_market_safe  : güvenli fetch wrapper (try/except + timeout)
- faz17_fetch_market       : provider seçip market datayı çeken fonksiyon (providers.py)

NOT:
- Paket dosyası MUTLAKA __init__.py olmalı. "init.py" işe yaramaz.
"""

from .faz17_market_fetcher import faz17_fetch_market_safe

try:
    # provider seçen ana fonksiyon
    from .providers import faz17_fetch_market
except Exception:
    # Import patlarsa bile main.py çökmeyecek (safe wrapper yine durur)
    faz17_fetch_market = None  # type: ignore

__all__ = ["faz17_fetch_market_safe", "faz17_fetch_market"] 
