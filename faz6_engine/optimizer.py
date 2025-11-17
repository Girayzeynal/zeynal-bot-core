# ================================================================
#                 FAZ-6 OPTIMIZER (BASİT)
# ================================================================

from __future__ import annotations
from typing import List, Dict, Any

Prediction = Dict[str, Any]


def optimize_predictions(
    predictions: List[Prediction],
    ml_meta: Dict[str, Any],
    mode: str,
    risk: bool = False,
    aggressive: bool = False,
    realtime: bool = False,
) -> List[Prediction]:
    """
    Basit stake / filtre mantığı.
    Gerçek bir optimizer yerine lightweight ayar yapıyor.
    """
    optimized: List[Prediction] = []

    for p in predictions:
        q = dict(p)

        edge = float(q.get("edge", 0) or 0.0)
        conf = float(q.get("confidence", 0) or 0.0)

        # Varsayılan stake
        base_stake = 1.0

        if risk:
            # daha korumacı
            base_stake = 0.5
            if edge < 0.03 or conf < 0.55:
                continue
        if aggressive:
            base_stake = 1.5
            if edge < 0.05 or conf < 0.58:
                continue
        if realtime:
            # gerçek zaman modunda hafif sıkılaştır
            if edge < 0.02 or conf < 0.56:
                continue

        # Edge + confidence'e göre stake modifiye
        stake = base_stake * (1.0 + edge * 5.0) * (0.5 + conf)

        q["recommended_stake"] = round(stake, 3)
        optimized.append(q)

    return optimized
