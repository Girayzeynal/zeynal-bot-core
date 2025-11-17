from __future__ import annotations
from typing import Dict, Any, List

Prediction = Dict[str, Any]


def build_real_predictions(memory: Dict[str, Any] | None) -> List[Prediction]:
    """
    REAL modu: gerçek zaman odaklı, daha temkinli tahminler.
    Şimdilik sabit örnek; ileride canlı veri ve hafızayı buraya bağlayacağız.
    """
    preds: List[Prediction] = [
        {
            "id": "NBA:LAL@GSW",
            "league": "NBA",
            "match": "LAL@GSW",
            "market": "spread",
            "selection": "LAL +4.5",
            "confidence": 0.58,
            "edge": 0.04,
        },
        {
            "id": "NBA:CHI@NYK",
            "league": "NBA",
            "match": "CHI@NYK",
            "market": "total",
            "selection": "UNDER 217.5",
            "confidence": 0.57,
            "edge": 0.035,
        },
        {
            "id": "EL:OLY@REAL",
            "league": "EuroLeague",
            "match": "OLY@REAL",
            "market": "moneyline",
            "selection": "REAL MADRID",
            "confidence": 0.6,
            "edge": 0.04,
        },
    ]
    return preds 
