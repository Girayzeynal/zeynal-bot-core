# FAZ-17 package surface (TEK DOĞRU GİRİŞ)
from .providers import odds_api_fetch_market as faz17_fetch_market  # provider
from .faz17_market_fetcher import faz17_fetch_market_safe  # safety wrapper

__all__ = ["faz17_fetch_market", "faz17_fetch_market_safe"] 
