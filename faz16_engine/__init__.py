"""
faz16_engine – Simulation Engine v4
===================================

Monte Carlo simülasyonları; FAZ-13 içinden kullanılmak üzere tasarlandı.
"""

# Monte Carlo simülasyonu fonksiyonunu dışa aktar
from .faz16_simulation import faz16_run_simulation

# Faz16Engine sınıfını güvenli bir şekilde içe aktarmak için importlib kullan.
# Önce .faz16_engine dosyasını, bulunamazsa .engine dosyasını yükler.
import importlib
try:
    _engine_module = importlib.import_module('.faz16_engine', package=__name__)
except ModuleNotFoundError:
    _engine_module = importlib.import_module('.engine', package=__name__)
Faz16Engine = getattr(_engine_module, 'Faz16Engine')

__all__ = [
    "faz16_run_simulation",
    "Faz16Engine",
]
