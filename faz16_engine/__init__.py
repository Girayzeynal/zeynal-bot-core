"""
faz16_engine - Simulation Engine v4
===============================

Monte Carlo simülasyonları; FAZ-13 içinden ve diğer fazlar tarafından kullanılmak üzere tasarlandı.
"""

# Gelişmiş simülasyonu ve Faz16Engine sınıfını dışa aktar
from .faz16_simulation import faz16_run_simulation
from .faz16_engine import Faz16Engine

__all__ = [
    "faz16_run_simulation",
    "Faz16Engine",
] 
