from .faz13_god_layer import run_faz13_with_god_layer

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

from .league_autodetect import guess_league
from .ultra_ocr_v3 import ultra_ocr_engine_v3

# FAZ-23 MAX ENGINE (varsa)
try:
    from .faz23_max import (
        Faz23MaxConfig,
        faz23_max_predict,
        faz23_max_comment,
        build_fusion_vector,
    )
except Exception:
    # Fly.io boot sırasında modül yoksa çökmesin
    Faz23MaxConfig = None
    faz23_max_predict = None
    faz23_max_comment = None
    build_fusion_vector = None
