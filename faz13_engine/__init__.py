# faz13_engine/__init__.py

"""
FAZ-13 Engine Paket Girişi

Burada sadece dışarıya açılacak ana fonksiyonlar re-export edilir.
main.py içindeki _safe_import çağrıları bu isimleri bekliyor.
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

__all__ = [
    # Normalizerlar
    "normalize_manual_text",
    "normalize_visual_meta",
    "normalize_api_data",
    "run_faz13_auto_pipeline",
    # Kupon motorları
    "faz13_daily_coupon",
    "faz13_upcoming_coupon",
    "faz13_league_coupon",
    "faz13_live_coupon",
    # GOD-LAYER
    "run_faz13_with_god_layer",
] 
