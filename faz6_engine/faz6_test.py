from __future__ import annotations
from typing import List, Dict, Any

Prediction = Dict[str, Any]

def run_faz6_test() -> Dict[str, Any]:
    """
    FAZ-6 TEST modunun standart dönüş formatı.
    """
    # Burada basit sabit örnek data döndürüyoruz.
    # Sen istediğinde gerçek test hesaplamasını ekleriz.
    preds: List[Prediction] = [
        {
            "id": "TEST:AAA@BBB",
            "league": "TEST",
            "match": "AAA@BBB",
            "market": "spread",
            "selection": "AAA -3.5",
            "confidence": 0.61,
            "edge": 0.032,
        }
    ]

    return {
        "status": "ok",
        "mode": "test",
        "result": {
            "predictions": preds,
            "portfolio": preds,
            "meta": {},
        },
        "context": {},
        "predictions": preds,
        "portfolio": preds,
    } 
