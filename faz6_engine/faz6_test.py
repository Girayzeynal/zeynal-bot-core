from __future__ import annotations
from typing import Dict, Any, List

Prediction = Dict[str, Any]


def build_test_predictions(memory: Dict[str, Any] | None) -> List[Prediction]:
    """
    Test modu için sabit birkaç örnek tahmin.
    """
    preds: List[Prediction] = [
        {
            "id": "NBA:LAC@PHX",
            "league": "NBA",
            "match": "LAC@PHX",
            "market": "spread",
            "selection": "LAC +7.5",
            "confidence": 0.6,
            "edge": 0.08,
        },
        {
            "id": "NBA:DAL@HOU",
            "league": "NBA",
            "match": "DAL@HOU",
            "market": "total",
            "selection": "OVER 231.5",
            "confidence": 0.61,
            "edge": 0.09,
        },
        {
            "id": "EL:OLY@PART",
            "league": "EuroLeague",
            "match": "OLY@PART",
            "market": "moneyline",
            "selection": "OLYMPIACOS",
            "confidence": 0.64,
            "edge": 0.08,
        },
    ]
    return preds
