# live_providers/provider_mackolik.py

import os
import logging
import requests
from typing import Optional, Dict, Any

log = logging.getLogger(__name__)


def fetch_live(query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Mackolik tabanlı canlı veri provider'ı (proxy API üzerinden).

    Çalışması için şu env değişkenlerinden biri AYARLANMIŞ olmalı:
        MACKOLIK_API_URL = "https://senin-api.com/live"

    Bu API sadece JSON dönderir. HTML scraping direkt bot içinde YASAK (ban riski).

    Eğer env yoksa => None → core fallback çalışır.
    """

    base_url = os.getenv("MACKOLIK_API_URL")
    if not base_url:
        log.warning("[MACKOLIK] API URL tanımlı değil → Skip.")
        return None

    # Parametreleri hazırlıyoruz
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
        resp = requests.get(base_url, params=params, timeout=5)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.error("[MACKOLIK] İstek hatası: %s", e, exc_info=True)
        return None

    # JSON içeriğini normalize ediyoruz
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
        "period_label": data.get("period") or data.get("period_label") or "Q1",
        "clock": data.get("clock") or "00:00",
        "status": data.get("status") or "LIVE",
        "pace": data.get("pace") or 98.5,
        "win_side_label": win_side_label,
        "win_prob": win_prob,
        "provider": "MACKOLIK",
    }
