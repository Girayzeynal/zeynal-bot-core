# -*- coding: utf-8 -*-
from __future__ import annotations

import time
import logging
from typing import Any, Callable, Dict, Optional

log = logging.getLogger("zeynal-core")


def faz17_fetch_market_safe(
    league: str,
    date_str: str,
    home: str,
    away: str,
    provider_fetch_func: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Crash etmez. Her zaman dict döner.
    provider_fetch_func verilmezse providers.faz17_fetch_market kullanır.
    """
    t0 = time.time()

    try:
        if provider_fetch_func is None:
            from .providers import faz17_fetch_market as provider_fetch_func  # local import to avoid circular

        data = provider_fetch_func(league=league, date_str=date_str, home=home, away=away)

        return {
            "used": True,
            "reason": "ok",
            "provider": (data.get("provider") if isinstance(data, dict) else None),
            "latency_ms": int((time.time() - t0) * 1000),
            "data": data,
        }

    except Exception as e:
        log.warning(f"[FAZ17] fetch_market_safe error: {e}")
        return {
            "used": False,
            "reason": f"safe_fetch_exception: {e}",
            "provider": None,
            "latency_ms": int((time.time() - t0) * 1000),
            "data": None,
        }
