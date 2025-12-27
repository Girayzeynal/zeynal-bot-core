"""
faz16_engine - Simulation Engine v4
==================================

Monte Carlo simülasyonları; FAZ-13 içinden kullanılmak üzere tasarlandı.
"""

# İleri düzey simülasyon fonksiyonunu içe aktar
from .faz16_simulation import faz16_run_simulation

# Modül dosyasını içe aktarıp sınıfı dışa aktar
from . import faz16_engine as _engine
Faz16Engine = _engine.Faz16Engine

__all__ = [
    "faz16_run_simulation",
    "Faz16Engine",
] 
