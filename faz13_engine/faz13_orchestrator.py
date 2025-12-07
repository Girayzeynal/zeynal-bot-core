import logging
from typing import Any, Dict, Optional

log = logging.getLogger("hoopbrain-faz13-orch")

# ================================================================
# GEÇERLİ / ORİJİNAL FAZ-13 FONKSİYONLARI
# ================================================================

def normalize_manual_text(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    return {"manual_text": text.strip()}


def normalize_visual_meta(meta: Dict[str, Any]) -> Dict[str, Any]:
    if not meta or not isinstance(meta, dict):
        return {}
    return {"visual_meta": meta}


def normalize_api_data(api_data: Dict[str, Any]) -> Dict[str, Any]:
    if not api_data or not isinstance(api_data, dict):
        return {}
    return {"api_data": api_data}


def run_faz13_auto_pipeline(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    FAZ-13 ana otomatik analiz işleyicisi.
    payload: dict (örneğin normalize_manual_text / normalize_visual_meta / normalize_api_data birleşimi)
    Bu versiyonda placeholder davranır — sadece gireni döner.
    """
    return {
        "status": "ok",
        "mode": "AUTO",
        "input": payload,
    }


# ================================================================
# 🟩 KU­PON MOTORU FONKSİYONLARI (EKLENDİ)
# ================================================================

def faz13_daily_coupon() -> Dict[str, Any]:
    """
    Günlük kupon önerisi üretir (placeholder).
    """
    return {
        "coupon_type": "daily",
        "status": "generated",
        "picks": ["FAZ13_DAILY_PICK_1", "FAZ13_DAILY_PICK_2"]
    }


def faz13_upcoming_coupon(upcoming_matches: Optional[list] = None) -> Dict[str, Any]:
    """
    Yaklaşan maç listesine göre kupon önerisi üretir.
    upcoming_matches: list of tuples veya dicts — bu örnekte opsiyonel / placeholder.
    """
    return {
        "coupon_type": "upcoming",
        "status": "generated",
        "picks": (upcoming_matches if upcoming_matches else ["UPCOMING_PICK_1", "UPCOMING_PICK_2"])
    }


def faz13_league_coupon(league_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Lig bazlı kupon önerisi.
    """
    return {
        "coupon_type": "league",
        "league": league_name or "UNKNOWN",
        "status": "generated",
        "picks": [f"{league_name or 'UNKNOWN'}_LEAGUE_PICK_1", f"{league_name or 'UNKNOWN'}_LEAGUE_PICK_2"]
    }


def faz13_live_coupon(live_context: Optional[dict] = None) -> Dict[str, Any]:
    """
    Canlı maç / canlı veri üzerinden kupon önerisi.
    live_context: dict — opsiyonel (örneğin live maç verisi)
    """
    return {
        "coupon_type": "live",
        "status": "generated",
        "context": live_context or {},
        "picks": ["LIVE_PICK_1", "LIVE_PICK_2"]
    }


# ================================================================
# EXPORT LİSTESİ
# ================================================================

__all__ = [
    "normalize_manual_text",
    "normalize_visual_meta",
    "normalize_api_data",
    "run_faz13_auto_pipeline",
    "faz13_daily_coupon",
    "faz13_upcoming_coupon",
    "faz13_league_coupon",
    "faz13_live_coupon",
] 
