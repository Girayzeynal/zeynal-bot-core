"""
faz8_engine – Pre-Behavior Engine
=================================

Görev:
- FAZ-7.9 hafızadan gelen ham istatistikleri normalize eder.
- Maç bazlı feature paketini hazırlar (pace, form, hücum, savunma skorları).
"""

from .faz8_behavior import (
    faz8_prepare_sample,
    faz8_update_global_state,
)

__all__ = [
    "faz8_prepare_sample",
    "faz8_update_global_state",
]
