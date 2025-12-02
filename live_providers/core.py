import json
import requests
from typing import Dict, Any

class HoopbrainLiveError(Exception):
    pass


def _safe_get(url: str, timeout: float = 4.0) -> Dict[str, Any]:
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        raise HoopbrainLiveError(str(e))


# ================================================================
# 🔥 MULTI-DATA FUSION ENGINE
# ================================================================
def get_live_match_global(match_code: str, mode: str = "prematch") -> Dict[str, Any]:
    """
    Tek fonksiyon → tüm sağlayıcılardan veri toplar, birleştirir.
    1) maçkolik
    2) flashscore
    3) nba
    4) euroleague
    5) hoopbrain-proxy (ek güvenli kaynak)
    """

    fusion = {
        "match_code": match_code,
        "mode": mode,
        "home": "HOME",
        "away": "AWAY",
        "league": "Unknown",
    }

    # -------------------------------------------
    # 1) Maçkolik (proxy üzerinden)
    # -------------------------------------------
    try:
        mdata = _safe_get(f"https://hoopbrain-proxy.fly.dev/mackolik/{match_code}")
        if isinstance(mdata, dict):
            fusion.update(mdata)
    except Exception:
        pass

    # -------------------------------------------
    # 2) FlashScore
    # -------------------------------------------
    try:
        fdata = _safe_get(f"https://hoopbrain-proxy.fly.dev/flash/{match_code}")
        if isinstance(fdata, dict):
            fusion.update(fdata)
    except Exception:
        pass

    # -------------------------------------------
    # 3) NBA
    # -------------------------------------------
    try:
        nba = _safe_get(f"https://hoopbrain-proxy.fly.dev/nba/{match_code}")
        if isinstance(nba, dict):
            fusion.update(nba)
    except Exception:
        pass

    # -------------------------------------------
    # 4) Euroleague
    # -------------------------------------------
    try:
        el = _safe_get(f"https://hoopbrain-proxy.fly.dev/euro/{match_code}")
        if isinstance(el, dict):
            fusion.update(el)
    except Exception:
        pass

    # -------------------------------------------
    # 5) Haber/Sakatlık
    # -------------------------------------------
    try:
        news = _safe_get(f"https://hoopbrain-proxy.fly.dev/news/{match_code}")
        if isinstance(news, dict):
            fusion["news"] = news.get("text", "")
    except Exception:
        fusion["news"] = ""

    return fusion
