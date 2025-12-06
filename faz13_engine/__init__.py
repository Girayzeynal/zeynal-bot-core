"""
FAZ-13 core package (light mode).

Bu profilde Ultra OCR v3 TORCH/EASYOCR kullanmadan,
tamamen kapalı tutuluyor. Sadece hafif Python modülleri
expose ediliyor.
"""

from .faz13_orchestrator import (
    normalize_manual_text,
    normalize_visual_meta,
    normalize_api_data,
    run_faz13_auto_pipeline,
    faz13_daily_coupon,
    faz13_upcoming_coupon,
    faz13_league_coupon,
    faz13_live_coupon,
)

from .faz13_god_layer import run_faz13_with_god_layer
from .league_autodetect import guess_league

__all__ = [
    "normalize_manual_text",
    "normalize_visual_meta",
    "normalize_api_data",
    "run_faz13_auto_pipeline",
    "faz13_daily_coupon",
    "faz13_upcoming_coupon",
    "faz13_league_coupon",
    "faz13_live_coupon",
    "run_faz13_with_god_layer",
    "guess_league",
]
