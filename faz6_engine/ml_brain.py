# ================================================================
#                 FAZ-6 ML BEYNİ (BASİT SÜRÜM)
# ================================================================

from __future__ import annotations
from typing import List, Dict, Any

Prediction = Dict[str, Any]
Memory = Dict[str, Any]


def evaluate_predictions(
    predictions: List[Prediction],
    memory: Memory | None,
    mode: str,
) -> Dict[str, Any]:
    """
    Basit ML meta değerlendirmesi.
    Gerçek model yerine lightweight istatistik topluyor.
    """
    memory = memory or {}

    cnt = len(predictions)
    avg_edge = 0.0
    avg_conf = 0.0
    if cnt:
        avg_edge = sum(float(p.get("edge", 0) or 0.0) for p in predictions) / cnt
        avg_conf = sum(float(p.get("confidence", 0) or 0.0) for p in predictions) / cnt

    leagues = {}
    for p in predictions:
        lg = str(p.get("league") or "UNKNOWN")
        leagues[lg] = leagues.get(lg, 0) + 1

    return {
        "mode": mode,
        "count": cnt,
        "avg_edge": round(avg_edge, 4),
        "avg_confidence": round(avg_conf, 4),
        "leagues": leagues,
        "memory_keys": list(memory.keys()),
    }
