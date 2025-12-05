# ================================================================
# live_providers/core.py — FAZ-CORE UYUMLU FULL SÜRÜM
# ================================================================

import os
import json
import logging
from typing import Dict, Any
import requests

# ------------------------------------------------
# LOG
# ------------------------------------------------
log = logging.getLogger(__name__)

# ------------------------------------------------
# PROXY AYAR
# ------------------------------------------------
PROXY_BASE = os.getenv("HOOPBRAIN_PROXY_URL", "https://hoopbrain-proxy.fly.dev").rstrip("/")
DEFAULT_TIMEOUT = float(os.getenv("LIVE_PROVIDER_TIMEOUT", "3.0"))

# ------------------------------------------------
# Özel hata tipi
# ------------------------------------------------
class HoopbrainLiveError(Exception):
    pass


# ------------------------------------------------
# Güvenli GET
# ------------------------------------------------
def _safe_get_json(path: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    url = f"{PROXY_BASE}/{path.lstrip('/')}"
    try:
        r = requests.get(url, params=params or {}, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        data = r.json()

        if not isinstance(data, dict):
            raise ValueError(f"Beklenmeyen JSON tipi: {type(data)}")

        return data

    except Exception as e:
        log.warning("live_providers: request error %s %s", url, e)
        raise HoopbrainLiveError(str(e))


# ------------------------------------------------
# GLOBAL MAÇ VERİ BİRLEŞTİRME (FAZ-22 / FAZ-23 UYUMLU)
# ------------------------------------------------
def get_live_match_global(match_key: str) -> Dict[str, Any]:
    """
    FAZ-23 motoru için tek giriş noktası.

    Proxy’den gelen JSON formatı:
        {
            "prematch": {...},
            "live": {...},
            "news": {...}
        }
    """

    try:
        bundle = _safe_get_json(f"meta/{match_key}")
    except HoopbrainLiveError:
        # PRO FALLBACK
        log.error("Proxy çöktü → FALLBACK MOD")
        return _fallback_live_packet(match_key)

    prematch = bundle.get("prematch", {}) or {}
    live     = bundle.get("live", {}) or {}
    news     = bundle.get("news", {}) or {}

    # ------------------------------------------------
    # FAZ-23 Fusion (FAZ-13 → FAZ-17 → FAZ-22 → FAZ-23)
    # ------------------------------------------------
    fusion = {
        # prematch
        "prematch_avg_total": prematch.get("avg_total", 0.0),
        "prematch_market_total": prematch.get("market_total", 0.0),
        "prematch_pace_index": prematch.get("pace_index", 1.0),
        "prematch_news_bias": news.get("prematch_bias", 0.0),

        # live
        "live_score_home": live.get("home_score", 0),
        "live_score_away": live.get("away_score", 0),
        "live_quarter": live.get("quarter", 1),
        "live_seconds_elapsed": live.get("seconds_elapsed", 0),
        "live_pace_index": live.get("pace_index", 1.0),
        "live_fouls_factor": live.get("fouls_factor", 0.0),
        "live_news_bias": news.get("live_bias", 0.0),

        # meta
        "match_key": match_key,
        "status": live.get("status", "ok"),
    }

    return fusion


# ------------------------------------------------
# FALLBACK MOD — Proxy çökerse sistem durmaz
# ------------------------------------------------
def _fallback_live_packet(match_key: str) -> Dict[str, Any]:
    log.warning("Fallback veri kullanılıyor (FAZ-23 SAFE MODE).")

    return {
        "match_key": match_key,
        "prematch_avg_total": 0.0,
        "prematch_market_total": 0.0,
        "prematch_pace_index": 1.0,
        "prematch_news_bias": 0.0,

        "live_score_home": 0,
        "live_score_away": 0,
        "live_quarter": 1,
        "live_seconds_elapsed": 0,
        "live_pace_index": 1.0,
        "live_fouls_factor": 0.0,
        "live_news_bias": 0.0,

        "status": "fallback"
    } 
