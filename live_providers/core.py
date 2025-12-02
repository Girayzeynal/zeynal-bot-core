import os
import logging
from typing import Dict, Any

import requests

log = logging.getLogger(__name__)

# HOOPBRAIN PROXY URL
PROXY_BASE = os.getenv("HOOPBRAIN_PROXY_URL", "https://hoopbrain-proxy.fly.dev").rstrip("/")

DEFAULT_TIMEOUT = float(os.getenv("LIVE_PROVIDER_TIMEOUT", "3.0"))


def _safe_get_json(path: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    url = f"{PROXY_BASE}{path}"
    try:
        r = requests.get(url, params=params or {}, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            return {}
        return data
    except Exception as e:
        log.warning("live_providers: request error %s %s", url, e)
        return {}


def get_live_match_global(match_key: str) -> Dict[str, Any]:
    """
    FAZ-23 için tek giriş noktası.
    Proxy'deki /meta/<match_key> endpoint'ini çağırır.

    Beklenen JSON formatı (hoopbrain-proxy tarafından üretilecek):
    {
      "match_key": "FENER@EFES",
      "prematch": {...},
      "live": {...},
      "news": {...}
    }
    """
    data = _safe_get_json(f"/meta/{match_key}")

    prematch = data.get("prematch") or {}
    live = data.get("live") or {}
    news = data.get("news") or {}

    # Bu sözlük FAZ-23 motoruna direkt geçilecek.
    fusion: Dict[str, Any] = {
        # prematch
        "prematch_avg_total": prematch.get("avg_total", 0.0),
        "prematch_market_total": prematch.get("market_total", 0.0),
        "prematch_pace_index": prematch.get("pace_index", 0.0),
        "prematch_news_bias": news.get("prematch_bias", 0.0),

        # live
        "prematch_center_guess": prematch.get("center_guess", prematch.get("market_total", 0.0)),
        "live_score_home": live.get("home_score", 0),
        "live_score_away": live.get("away_score", 0),
        "live_quarter": live.get("quarter", 1),
        "live_seconds_elapsed": live.get("seconds_elapsed", 0),
        "live_pace_index": live.get("pace_index", 1.0),
        "live_fouls_factor": live.get("fouls_factor", 0.0),
        "live_news_bias": news.get("live_bias", 0.0),
    }

    return fusion 
