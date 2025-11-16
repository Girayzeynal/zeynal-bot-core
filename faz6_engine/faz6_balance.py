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
    Basit portföy karıştırıcı:
    - Risk'ten güvenli parçalar
    - Edge'den yüksek edge'li ama limitli sayı
    - Auto'dan genel denge
    """
    portfolio: List[Dict[str, Any]] = []

    # Risk'ten düşük riskli olanları çek
    for p in risk_preds:
        if p.get("risk_level") in ("low", "medium"):
            portfolio.append(dict(p))

    # Edge'den gerçekten güçlü olanları ekle (adet limiti ile)
    edge_strong = [
        p for p in edge_preds
        if p.get("edge", 0.0) >= 0.07 and p.get("confidence", 0) >= 0.62
    ][:5]

    for p in edge_strong:
        q = dict(p)
        q.setdefault("tag", "edge_balance")
        portfolio.append(q)

    # Auto'dan portföyü tamamla
    for p in auto_preds[:10]:
        q = dict(p)
        q.setdefault("tag", "auto_balance")
        portfolio.append(q)

    # Basit tekrar temizliği (id + market'e göre)
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
    Balance modu: risk + edge + auto çıktılarından dengeli portföy.
    """
    auto_res = run_faz6_auto()
    risk_res = run_faz6_risk()
    edge_res = run_faz6_edge()

    auto_preds = auto_res.get("predictions", [])
    risk_preds = risk_res.get("predictions", [])
    edge_preds = edge_res.get("predictions", [])

    portfolio = _mix_portfolio(auto_preds, risk_preds, edge_preds)

    return {
        "mode": "balance",
        "portfolio": portfolio,
        "sources": {
            "auto": auto_res.get("ml_meta", {}),
            "risk": risk_res.get("ml_meta", {}),
            "edge": edge_res.get("ml_meta", {}),
        },
        "context": context or {},
    } 
