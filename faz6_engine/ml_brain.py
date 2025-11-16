# ================================================================
#                    FAZ-6 ML_BRAIN (BASİT ÇEKİRDEK)
# ================================================================

from __future__ import annotations
from typing import List, Dict, Any


def evaluate_predictions(
    predictions: List[Dict[str, Any]],
    memory: Dict[str, Any] | None = None,
    mode: str = "auto",
) -> Dict[str, Any]:
    """
    Çok basit bir istatistiksel değerlendirme:
    - Ortalama güven
    - Ortalama edge
    - Tahmini risk skoru
    - Streak bilgisi (hafızadan)
    """

    memory = memory or {}
    n = len(predictions)

    if n == 0:
        return {
            "mode": mode,
            "count": 0,
            "avg_confidence": 0.0,
            "avg_edge": 0.0,
            "risk_score": 0.0,
            "loss_streak": memory.get("loss_streak", 0),
        }

    total_conf = 0.0
    total_edge = 0.0

    for p in predictions:
        total_conf += float(p.get("confidence", 0.5))
        total_edge += float(p.get("edge", 0.0))

    avg_conf = total_conf / n
    avg_edge = total_edge / n

    loss_streak = int(memory.get("loss_streak", 0))

    # Çok kaba risk skor modeli: yüksek edge + yüksek conf = düşük risk
    base_risk = 1.0 - avg_conf
    if avg_edge > 0:
        base_risk *= max(0.3, 1.0 - avg_edge * 3)

    # Loss streak varsa riski yükselt
    if loss_streak > 0:
        base_risk *= (1.0 + min(0.5, loss_streak * 0.1))

    risk_score = max(0.0, min(1.0, base_risk))

    return {
        "mode": mode,
        "count": n,
        "avg_confidence": round(avg_conf, 3),
        "avg_edge": round(avg_edge, 3),
        "risk_score": round(risk_score, 3),
        "loss_streak": loss_streak,
    } 
