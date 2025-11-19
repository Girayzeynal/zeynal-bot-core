from __future__ import annotations
from typing import Dict, Any, List

Prediction = Dict[str, Any]

def build_real_predictions(memory: Dict[str, Any] | None) -> List[Prediction]:
    preds: List[Prediction] = [
        {
            "id": "NBA:LAL@GSW",
            "league": "NBA",
            "match": "LAL@GSW",
            "market": "spread",
            "selection": "LAL +4.5",
            "confidence": 0.58,
            "edge": 0.04,
        }
    ]
    return preds


def run_faz6_real(context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    preds = build_real_predictions(None)

    return {
        "status": "ok",
        "mode": "real",
        "result": {
            "predictions": preds,
            "portfolio": preds,
        },
        "context": context or {},
        "predictions": preds,
        "portfolio": preds,
    } 
