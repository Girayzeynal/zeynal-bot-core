from __future__ import annotations
from typing import Dict, Any, List

Prediction = Dict[str, Any]


def _base_stake(conf: float, edge: float) -> float:
    """
    Çok basit bir stake fonksiyonu.
    """
    raw = 0.1 + conf * 0.3 + edge * 1.0
    return max(0.05, min(raw, 0.5))


def optimize_predictions(
    predictions: List[Prediction],
    ml_meta: Dict[str, Any],
    mode: str,
    *,
    risk: bool = False,
    aggressive: bool = False,
    realtime: bool = False,
) -> List[Prediction]:
    out: List[Prediction] = []

    for p in predictions:
        q = dict(p)

        conf = float(q.get("confidence", 0.6))
        edge = float(q.get("edge", 0.02))

        stake = _base_stake(conf, edge)

        if risk:
            stake *= 0.8
            q["risk_level"] = "low" if conf >= 0.7 else "medium"
        elif aggressive:
            stake *= 1.25
            q["risk_level"] = "high"
        elif realtime:
            stake *= 0.9
            q["risk_level"] = "medium"
        else:
            q.setdefault("risk_level", "medium")

        stake = max(0.05, min(stake, 0.6))
        q["stake"] = round(stake, 3)

        out.append(q)

    return out
