# faz23_engine/faz23_core.py
from __future__ import annotations

import time
from typing import Any, Dict, Optional, List

from .faz23_datahub import memory_put


def _match_key(league: str, date_str: str, home: str, away: str) -> str:
    return f"{league}::{date_str}::{home}::{away}".upper()


def _error_tags(faz13: Dict[str, Any], faz22: Optional[Dict[str, Any]] = None) -> List[str]:
    """
    Basit hata/uyarı etiketleri.
    (Gerçek öğrenme loop'u burada büyütülecek.)
    """
    tags: List[str] = []

    band = faz13.get("band")
    if isinstance(band, list) and len(band) == 2:
        try:
            width = float(band[1]) - float(band[0])
            if width > 18:
                tags.append("VAR_HIGH")
            elif width < 8:
                tags.append("VAR_LOW")
        except Exception:
            pass

    market = faz13.get("market", {})
    if isinstance(market, dict):
        if market.get("used"):
            conf = float(market.get("confidence", 0.0) or 0.0)
            if conf >= 0.75:
                tags.append("MARKET_STRONG")
            elif conf <= 0.35:
                tags.append("MARKET_WEAK")

    if faz22 and isinstance(faz22, dict):
        conf2 = float(faz22.get("confidence", 0.0) or 0.0)
        if conf2 >= 0.80:
            tags.append("META_CONF_HIGH")
        elif conf2 <= 0.55:
            tags.append("META_CONF_LOW")

    return tags


def faz23_memory_write(
    *,
    league: str,
    date_str: str,
    home: str,
    away: str,
    faz13_result: Dict[str, Any],
    faz22_result: Optional[Dict[str, Any]] = None,
    actual_total: Optional[float] = None,
) -> Dict[str, Any]:
    """
    FAZ-23 = Memory only.
    - Skor üretmez
    - Meta üretmez
    - Orchestrate etmez
    """
    ts = int(time.time())
    key = _match_key(league, date_str, home, away)

    tags = _error_tags(faz13_result, faz22_result)

    record = {
        "ts": ts,
        "key": key,
        "league": league,
        "date": date_str,
        "home": home,
        "away": away,
        "faz13": faz13_result,
        "faz22": faz22_result,
        "actual_total": actual_total,
        "tags": tags,
    }

    stored = memory_put(key, record)

    return {"stored": bool(stored), "tags": tags, "ts": ts, "engine": "FAZ-23-MEMORY"}
