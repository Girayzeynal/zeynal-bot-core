# ============================================================
# FAZ-13 ENGINE __init__.py (STABLE & MATCHING REAL FUNCTIONS)
# ============================================================

# --- FAZ-13 ORCHESTRATOR ---
from .faz13_orchestrator import (
    normalize_manual_text,
    normalize_visual_meta,
    normalize_api_data,
    run_faz13_auto_pipeline,
)

# --- GOD LAYER ---
from .faz13_god_layer import run_faz13_with_god_layer

# --- LEAGUE DETECTOR ---
from .league_autodetect import guess_league

# --- ULTRA OCR ENGINE ---
from .ultra_ocr_v3 import ultra_ocr_engine_v3


__all__ = [
    "normalize_manual_text",
    "normalize_visual_meta",
    "normalize_api_data",
    "run_faz13_auto_pipeline",

    "run_faz13_with_god_layer",

    "guess_league",
    "ultra_ocr_engine_v3",
] 
