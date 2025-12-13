# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, Optional


def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip().replace(",", ".")
        return float(s)
    except Exception:
        return None


def faz17_market_adjust(market_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    FAZ-17 market çıktısını stabilize eder.

    Hedef: main.py / FAZ-13 orchestrator farklı formatları da yese bile
    burada "tek tip" hale getirelim.

    Beklenen anahtarlar:
      - used: bool
      - main_total: float|None
      - confidence: float (0..1)
      - sources: list
      - error/reason: str
    """
    md = dict(market_data or {})

    # used
    used = md.get("used")
    if used is None:
        used = bool(md.get("ok"))  # fetcher ok ise used say
    md["used"] = bool(used)

    # main_total / total_line
    mt = _safe_float(md.get("main_total"))
    if mt is None:
        mt = _safe_float(md.get("total_line"))
    if mt is not None:
        md["main_total"] = float(mt)
        md["total_line"] = float(mt)
    else:
        md["main_total"] = None
        md["total_line"] = None

    # confidence
    conf = _safe_float(md.get("confidence"))
    if conf is None:
        conf = _safe_float(md.get("market_confidence"))
    if conf is None:
        conf = 0.0
    conf = max(0.0, min(1.0, float(conf)))
    md["confidence"] = conf
    md["market_confidence"] = conf

    # sources
    srcs = md.get("sources")
    if not isinstance(srcs, list):
        srcs = []
    md["sources"] = srcs

    # reason / error
    if not md["used"]:
        if not md.get("reason") and not md.get("error"):
            md["error"] = "NO_MARKET_DATA"
            md["reason"] = "NO_MARKET_DATA"

    return md
