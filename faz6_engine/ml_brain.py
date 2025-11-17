from __future__ import annotations
from typing import Dict, Any, List

Prediction = Dict[str, Any]


def evaluate_predictions(
    predictions: List[Prediction],
    memory: Dict[str, Any],
    mode: str,
) -> Dict[str, Any]:
    """
    Basit ML-beyni:
        - ortalama güven
        - ortalama edge
        - seçim sayısı
        - hafızadan birkaç özet
    """
    if not predictions:
        return {
            "mode": mode,
            "count": 0,
            "avg_confidence": 0.0,
            "avg_edge": 0.0,
            "notes": "no_predictions",
        }

    total_conf = 0.0
    total_edge = 0.0

    for p in predictions:
        total_conf += float(p.get("confidence", 0.0))
        total_edge += float(p.get("edge", 0.0))

    n = len(predictions)
    return {
        "mode": mode,
        "count": n,
        "avg_confidence": round(total_conf / n, 3),
        "avg_edge": round(total_edge / n, 3),
        "memory_keys": list(memory.keys())[:10],
    }
