# FAZ-23 ENGINE __init__.py

# --- FAZ-13 GOD LAYER ---
from faz13_engine.faz13_god_layer import run_faz13_with_god_layer

# --- FAZ-13 ORCHESTRATOR ---
from faz13_engine.faz13_orchestrator import (
    normalize_manual_text,
    normalize_visual_meta,
    normalize_api_data,
    run_faz13_auto_pipeline,
    faz13_daily_coupon,
    faz13_upcoming_coupon,
    faz13_league_coupon,
    faz13_live_coupon,
)

# --- LEAGUE AUTO-DETECT ---
from faz13_engine.league_autodetect import guess_league

# --- ULTRA OCR ENGINE v3 ---
from faz13_engine.ultra_ocr_v3 import ultra_ocr_engine_v3

# --- FAZ-23 MAX ENGINE (opsiyonel) ---
try:
    from .faz23_max import (
        Faz23MaxConfig,
        faz23_max_predict,
        faz23_max_comment,
        build_fusion_vector,
    )
except ImportError:
    Faz23MaxConfig = None
    faz23_max_predict = None
    faz23_max_comment = None
    build_fusion_vector = None

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
    # FAZ-23 MAX (opsiyonel)
    "Faz23MaxConfig",
    "faz23_max_predict",
    "faz23_max_comment",
    "build_fusion_vector",
] 
