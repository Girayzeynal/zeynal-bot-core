# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, Optional


def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def faz17_apply_totals_hint(
    *,
    predicted_total: Optional[float],
    market_data: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    FAZ-13 çıktısı total/band üretmiyorsa, market totals_line'ı "hint" olarak verir.
    Burada agresif değiştirmiyoruz; sadece sağlam sinyal olarak ekliyoruz.
    """
    if not market_data:
        return {"used": False, "reason": "no_market_data"}

    line = _safe_float(market_data.get("totals_line"))
    if line is None:
        return {"used": False, "reason": "no_totals_line"}

    # predicted_total yoksa line'ı öner
    if predicted_total is None:
        return {"used": True, "reason": "inject_line_as_total", "suggested_total": float(line)}

    # predicted_total varsa küçük delta bilgisi
    return {"used": True, "reason": "compare_total_to_line", "line": float(line), "delta": float(predicted_total - line)}
