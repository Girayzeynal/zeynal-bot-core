from __future__ import annotations
from typing import Dict, Any, List

from .auto import run_faz6_auto
from .faz6_risk import run_faz6_risk
from .faz6_edge import run_faz6_edge

Prediction = Dict[str, Any]
EngineResult = Dict[str, Any]


def _mix(auto_preds, risk_preds, edge_preds):
    portfolio = []

    portfolio.extend(risk_preds[:5])
    portfolio.extend(edge_preds[:3])
    portfolio.extend(auto_preds[:10])

    seen = set()
    uniq = []

    for p in portfolio:
        key = (p.get("id"), p.get("market"))
        if key not in seen:
            seen.add(key)
            uniq.append(p)

    return uniq


def run_faz6_balance(context: Dict[str, Any] | None = None, mode="auto") -> Dict[str, Any]:
    auto_res = run_faz6_auto()
    risk_res = run_faz6_risk()
    edge_res = run_faz6_edge()

    auto_preds = auto_res["result"]["predictions"]
    risk_preds = risk_res["result"]["predictions"]
    edge_preds = edge_res["result"]["predictions"]

    final = _mix(auto_preds, risk_preds, edge_preds)

    return {
        "status": "ok",
        "mode": "balance",
        "result": {
            "predictions": final,
            "portfolio": final,
            "meta": {},
        },
        "context": context or {},
        "predictions": final,
        "portfolio": final,
    } 
