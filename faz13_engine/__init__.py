# faz13_engine/__init__.py
"""
FAZ-13 engine package

Bu paket import edilirken ASLA crash olmamalı.
- main.py içinde _safe_import zaten modülleri tek tek güvenli şekilde çekiyor.
- Burada sadece gerçekten var olan fonksiyonları dışarı açıyoruz.
"""

from .faz13_orchestrator import run_faz13_auto_pipeline
from .faz13_god_layer import run_faz13_with_god_layer
from .league_autodetect import guess_league

__all__ = [
    "run_faz13_auto_pipeline",
    "run_faz13_with_god_layer",
    "guess_league",
] 
