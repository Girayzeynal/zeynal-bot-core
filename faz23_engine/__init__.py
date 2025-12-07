# ============================================================
# FAZ-23 ENGINE __init__.py (STABLE + CORRECT IMPORT PATHS)
# ============================================================

# --- FAZ-13 GOD LAYER (FAZ-23 içinde kullanılan) ---
from .faz13_god_layer import run_faz13_with_god_layer

# --- FAZ-13 ORCHESTRATOR (FAZ-23 içinde de kullanılıyor) ---
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

# --- LEAGUE AUTO-DETECT ---
from .league_autodetect import guess_league

# --- ULTRA OCR ENGINE v3 ---
from .ultra_ocr_v3 import ultra_ocr_engine_v3


# ============================================================
# FAZ-23 MAX ENGINE (OPSİYONEL)
# Modül yoksa Fly.io boot sırasında çökmesin diye try/except.
# ============================================================
try:
    from .faz23_max import (
        Faz23MaxConfig,
        faz23_max_predict,
        faz23_max_comment,
        build_fusion_vector,
    )
except Exception:
    Faz23MaxConfig = None
    faz23_max_predict = None
    faz23_max_comment = None
    build_fusion_vector = None


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

    # FAZ-23 MAX (opsiyonel)
    "Faz23MaxConfig",
    "faz23_max_predict",
    "faz23_max_comment",
    "build_fusion_vector",
]
