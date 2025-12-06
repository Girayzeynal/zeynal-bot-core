"""
FAZ-13 core package (light mode).

Bu profilde:
- Ultra OCR v3 gibi ağır şeyler __init__ içinden import edilmiyor.
- Sadece gerçekten var olan hafif fonksiyonlar expose ediliyor.
"""

from .league_autodetect import guess_league
from .faz13_orchestrator import run_faz13_auto_pipeline

__all__ = [
    "guess_league",
    "run_faz13_auto_pipeline",
] 
