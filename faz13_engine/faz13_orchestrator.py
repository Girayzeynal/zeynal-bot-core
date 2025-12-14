# ================================================================
# 🧠 FAZ-13 ORCHESTRATOR (ELITE CORE AWARE)
# ================================================================

import logging
from typing import Dict, Any

log = logging.getLogger(__name__)

# ================================================================
# 🧠 ELITE CORE IMPORTS
# ================================================================
from core.elite_league_registry import (
    resolve_league_layer,
    enrichment_sources,
)

# ================================================================
# 🔹 NORMALIZATION HELPERS (MEVCUT YAPIYA UYUMLU)
# ================================================================
def normalize_manual_text(text: str) -> Dict[str, Any]:
    return {
        "source": "manual",
        "raw_text": text,
    }

def normalize_api_data(api_data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source": "api",
        "data": api_data,
    }

def normalize_visual_meta(meta: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source": "visual",
        "meta": meta,
    }

# ================================================================
# 🎯 FAZ-13 CORE PIPELINE
# ================================================================
def run_faz13_auto_pipeline(
    league: str,
    home: str,
    away: str,
    date_str: str,
    market_data: Dict[str, Any] = None,
    market_meta: Dict[str, Any] = None,
    extra_inputs: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """
    Main FAZ-13 orchestrator entrypoint.
    """

    # ------------------------------------------------------------
    # League & layer
    # ------------------------------------------------------------
    league_layer = resolve_league_layer(league)

    # ------------------------------------------------------------
    # Market awareness
    # ------------------------------------------------------------
    market_used = False
    market_confidence = None
    market_reason = None

    if market_meta:
        market_used = market_meta.get("market", {}).get("used", False)
        market_confidence = market_meta.get("market", {}).get("confidence")
        market_reason = market_meta.get("market", {}).get("reason")

    # ------------------------------------------------------------
    # Enrichment (profile only)
    # ------------------------------------------------------------
    enrichment = enrichment_sources(league_layer)

    # ------------------------------------------------------------
    # 🔬 SIMULATION WEIGHTS (KRİTİK)
    # ------------------------------------------------------------
    weights = {
        "market": 0.0,
        "enrichment": 0.0,
        "base_model": 1.0,
    }

    if market_used:
        # Primary market → güçlü etki
        if market_confidence == "PRIMARY":
            weights["market"] = 1.0
        # Secondary test market → sınırlı
        elif market_confidence == "SECONDARY_TEST":
            weights["market"] = 0.4
        # FIBA isolated
        elif market_confidence == "FIBA_ISOLATED":
            weights["market"] = 0.6
    else:
        weights["market"] = 0.0

    if enrichment:
        weights["enrichment"] = 0.5

    # ------------------------------------------------------------
    # 🧠 CORE SIMULATION (placeholder – mevcut modelin burada çalışır)
    # ------------------------------------------------------------
    simulation_result = {
        "predicted_score_band": None,
        "confidence": None,
    }

    # ÖRNEK: burada senin mevcut skor / tempo / varyans modelin çalışır
    # Biz sadece meta ve ağırlıkları doğru bağlıyoruz

    # ------------------------------------------------------------
    # 📦 FINAL OUTPUT
    # ------------------------------------------------------------
    output = {
        "match": {
            "league": league,
            "league_layer": league_layer,
            "date": date_str,
            "home": home,
            "away": away,
        },
        "market": {
            "used": market_used,
            "confidence": market_confidence,
            "reason": market_reason,
        },
        "enrichment": enrichment,
        "weights": weights,
        "simulation": simulation_result,
        "debug": {
            "market_meta": market_meta,
        },
    }

    return output

# ================================================================
# 📅 DAILY COUPON (MEVCUT İSİM KORUNDU)
# ================================================================
def faz13_daily_coupon(matches: list) -> Dict[str, Any]:
    """
    Aggregate multiple FAZ-13 outputs into a daily coupon.
    """
    coupon = {
        "matches": matches,
        "summary": {
            "total_matches": len(matches),
            "market_used": sum(1 for m in matches if m.get("market", {}).get("used")),
        },
    }
    return coupon
