# ============================================================
# FAZ-13 ENGINE __init__.py (STABLE)
# ============================================================

# --- FAZ-13 ORCHESTRATOR ---
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

# --- FAZ-13 GOD LAYER ---
from .faz13_god_layer import run_faz13_with_god_layer

# --- LEAGUE AUTO-DETECT ---
from .league_autodetect import guess_league

# --- ULTRA OCR ENGINE v3 ---
from .ultra_ocr_v3 import ultra_ocr_engine_v3


# ============================================================
# EXPORTS
# ============================================================
__all__ = [
    # FAZ-13 core
    "normalize_manual_text",
    "normalize_visual_meta",
    "normalize_api_data",
    "run_faz13_auto_pipeline",
    "faz13_daily_coupon",
    "faz13_upcoming_coupon",
    "faz13_league_coupon",
    "faz13_live_coupon",

    # GOD LAYER
    "run_faz13_with_god_layer",

    # OCR + league detect
    "guess_league",
    "ultra_ocr_engine_v3",
]
