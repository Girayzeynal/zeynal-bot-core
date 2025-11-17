from __future__ import annotations
from typing import Dict, Any, List

Prediction = Dict[str, Any]


def build_edge_predictions(memory: Dict[str, Any] | None) -> List[Prediction]:
    """
    EDGE modu: yüksek edge odaklı tahminler.
    Hafıza doluysa ileride buradan ince ayar yapabiliriz.
    """
    preds: List[Prediction] = [
        {
            "id": "NBA:BOS@DEN",
            "league": "NBA",
            "match": "BOS@DEN",
            "market": "spread",
            "selection": "BOS -2.5",
            "confidence": 0.63,
            "edge": 0.07,
        },
        {
            "id": "NBA:MIA@MIL",
            "league": "NBA",
            "match": "MIA@MIL",
            "market": "total",
            "selection": "OVER 221.5",
            "confidence": 0.64,
            "edge": 0.08,
        },
        {
            "id": "EL:FENER@EFES",
            "league": "EuroLeague",
            "match": "FENER@EFES",
            "market": "moneyline",
            "selection": "FENERBAHÇE",
            "confidence": 0.66,
            "edge": 0.09,
        },
    ]
    return preds
