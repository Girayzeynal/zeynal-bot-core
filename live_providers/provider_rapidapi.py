# live_providers/provider_rapidapi.py
import os
import logging
from typing import Optional, Dict, Any

import requests

log = logging.getLogger(__name__)


def fetch_live(query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    RapidAPI tabanlı canlı veri provider'ı için iskelet.

    Gerekli env değişkenleri:
      - RAPIDAPI_ENDPOINT  (örn: https://example.p.rapidapi.com/live)
      - RAPIDAPI_KEY
      - RAPIDAPI_HOST      (RapidAPI'de verilen host adı)

    Bu env'lerden biri yoksa None döner → core fallback'e geçer.
    """
    endpoint = os.getenv("RAPIDAPI_ENDPOINT")
    api_key = os.getenv("RAPIDAPI_KEY")
    api_host = os.getenv("RAPIDAPI_HOST")

    if not endpoint or not api_key or not api_host:
        return None

    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": api_host,
    }

    params: Dict[str, Any] = {}
    mode = query.get("mode")

    if mode == "ID" and query.get("match_id"):
        params["match_id"] = query["match_id"]
    else:
        if query.get("league"):
            params["league"] = query["league"]
        if query.get("home"):
            params["home"] = query["home"]
        if query.get("away"):
            params["away"] = query["away"]

    try:
        resp = requests.get(endpoint, headers=headers, params=params, timeout=5)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.error("[RAPIDAPI] İstek hatası: %s", e, exc_info=True)
        return None

    # RapidAPI cevabını unified formata map ediyoruz.
    home_score = data.get("home_score") or 0
    away_score = data.get("away_score") or 0

    win_side_label = data.get("win_side_label")
    if not win_side_label:
        win_side_label = "HOME" if home_score >= away_score else "AWAY"

    win_prob = data.get("win_prob")
    if win_prob is None:
        win_prob = 0.55 if win_side_label == "HOME" else 0.45

    return {
        "league": data.get("league"),
        "match_id": data.get("match_id"),
        "home_name": data.get("home_name"),
        "away_name": data.get("away_name"),
        "home_score": home_score,
        "away_score": away_score,
        "period_label": data.get("period_label") or data.get("period"),
        "clock": data.get("clock"),
        "status": data.get("status") or "LIVE",
        "pace": data.get("pace") or 98.5,
        "win_side_label": win_side_label,
        "win_prob": float(win_prob),
        "provider": "RAPIDAPI",
    }
