"""
faz9_engine – Trend & Behavior Engine
=====================================

FAZ-9.1: Trend & Noise Filter
FAZ-9.2: Behavior Curve Engine
"""

from .faz9_behavior import (
    faz9_compute_trend,
    faz9_behavior_curve,
)

__all__ = [
    "faz9_compute_trend",
    "faz9_behavior_curve",
]
