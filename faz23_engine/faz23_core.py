# faz23_engine/faz23_core.py
"""
FAZ-23 CORE BRIDGE

Bu dosya sadece faz23_max içindeki asıl motoru dışarı açan
ince bir köprü. Her yerden aynı import çalışsın diye var.
"""

from .faz23_max import Faz23MaxConfig, faz23_max_predict

__all__ = ["Faz23MaxConfig", "faz23_max_predict"]
