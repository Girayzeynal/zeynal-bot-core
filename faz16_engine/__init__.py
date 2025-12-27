"""
faz16_engine – Simulation Engine v4
===================================

Monte Carlo simülasyonları; FAZ-13 içinden kullanılmak üzere tasarlandı.
"""

# Monte Carlo simülasyonu fonksiyonunu dışa aktar
from .faz16_simulation import faz16_run_simulation

# Faz16Engine sınıfını güvenli bir şekilde içe aktarmak için importlib kullan.
# Bu sayede paket henüz tam inşa edilirken yeniden kendisini import etmeye çalışmaz.
import importlib
_engine_module = importlib.import_module(__name__ + '.faz16_engine')
Faz16Engine = getattr(_engine_module, 'Faz16Engine')

__all__ = [
    "faz16_run_simulation",
    "Faz16Engine",
] 
