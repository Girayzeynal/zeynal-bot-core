# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple, Callable

from .providers import odds_api_fetch_market


MarketProviderFunc = Callable[..., Tuple[Optional[Dict[str, Any]], Dict[str, Any]]]


def _ts() -> int:
    return int(time.time())


def faz17_fetch_market(
    *,
    league: str,
    date_str: str,
    home: str,
    away: str,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    Provider seçen 'normal' fetch.
    Şu an: ODDS API totals market.
    """
    return odds_api_fetch_market(league=league, date_str=date_str, home=home, away=away)


def faz17_fetch_market_safe(
    *,
    league: str,
    date_str: str,
    home: str,
    away: str,
    provider_fetch_func: Optional[MarketProviderFunc] = None,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    MAIN.PY burayı çağırır. İmza SABİT.
    provider_fetch_func verilirse onu kullanır; verilmezse faz17_fetch_market kullanır.
    """
    try:
        fn = provider_fetch_func or faz17_fetch_market
        md, meta = fn(league=league, date_str=date_str, home=home, away=away)
        if not isinstance(meta, dict):
            meta = {"used": False, "reason": "meta_not_dict", "provider": None, "ts": _ts()}
        meta.setdefault("ts", _ts())
        return md, meta
    except Exception as e:
        return None, {"used": False, "reason": f"safe_fetch_exception:{e}", "provider": None, "ts": _ts()}
