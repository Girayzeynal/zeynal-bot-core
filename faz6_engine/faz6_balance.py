# ================================================================
#                 FAZ-6 BALANCE MODÜLÜ
# ================================================================

from __future__ import annotations
from typing import Dict, Any, List

from .faz6_core import run_faz6_auto, run_faz6_risk, run_faz6_edge


def _mix_portfolio(
    auto_preds: List[Dict[str, Any]],
    risk_preds: List[Dict[str, Any]],
    edge_preds: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    DENGELİ PORTFÖY:
    - Risk: düşük/orta risk seçim
    - Edge: yüksek edge + güven filtresi
    - Auto: genel denge
    """
    portfolio: List[Dict[str, Any]] = []

    # Risk
    for p in risk_preds:
        if p.get("risk_level") in ("low", "medium"):
            portfolio.append(dict(p))

    # Edge (sınırlı adet güçlü seçim)
    strong = [
        p for p in edge_preds
        if p.get("edge", 0) >= 0.07 and p.get("confidence", 0) >= 0.62
    ][:5]
    for p in strong:
        q = dict(p)
        q.setdefault("tag", "edge_balance")
        portfolio.append(q)

    # Auto'dan tamamla
    for p in auto_preds[:10]:
        q = dict(p)
        q.setdefault("tag", "auto_balance")
        portfolio.append(q)

    # Tekilleştirme (id + market)
    seen = set()
    unique: List[Dict[str, Any]] = []
    for p in portfolio:
        key = (p.get("id"), p.get("market"))
        if key not in seen:
            seen.add(key)
            unique.append(p)

    return unique


def run_faz6_balance(context: Dict[str, Any] | None = None, mode: str = "auto") -> Dict[str, Any]:
    """
    BALANCE modu — FAZ-6 standart formatına uygun çıktı üretir.
    """
    if context is None:
        context = {}

    auto_res = run_faz6_auto()
    risk_res = run_faz6_risk()
    edge_res = run_faz6_edge()

    # Her modun içinden predictions çek
    auto_preds = auto_res["result"]["predictions"]
    risk_preds = risk_res["result"]["predictions"]
    edge_preds = edge_res["result"]["predictions"]

    portfolio = _mix_portfolio(auto_preds, risk_preds, edge_preds)

    result = {
        "predictions": portfolio,
        "portfolio": portfolio,
        "meta": {
            "sources": {
                "auto": auto_res["result"]["ml_meta"],
                "risk": risk_res["result"]["ml_meta"],
                "edge": edge_res["result"]["ml_meta"],
            }
        },
    }

    return {
        "status": "ok",
        "mode": "balance",
        "result": result,
        "context": context,
        # geri uyum:
        "predictions": portfolio,
        "portfolio": portfolio,
    }
