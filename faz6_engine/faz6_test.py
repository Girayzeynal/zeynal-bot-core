# FAZ-6 TEST MODÜLÜ (DÜZELTİLMİŞ)

from __future__ import annotations
from typing import Dict, Any, List

Prediction = Dict[str, Any]


def build_test_predictions(memory: Dict[str, Any] | None) -> List[Prediction]:
    """
    FAZ-6 test modu için örnek tahmin datası.
    Telegram formatı ve FAZ-6 standartlarına %100 uyumludur.
    """

    preds: List[Prediction] = [
        {
            "id": "NBA:LAC@PHX",
            "league": "NBA",
            "match": "LAC@PHX",
            "market": "spread",
            "pick": "LAC +7.5",
            "confidence": 0.60,
            "edge": 0.08,
            "recommended_stake": 2,
        },
        {
            "id": "NBA:DAL@HOU",
            "league": "NBA",
            "match": "DAL@HOU",
            "market": "total",
            "pick": "OVER 231.5",
            "confidence": 0.61,
            "edge": 0.09,
            "recommended_stake": 3,
        },
        {
            "id": "EL:OLY@PART",
            "league": "EuroLeague",
            "match": "OLY@PART",
            "market": "moneyline",
            "pick": "OLYMPIACOS",
            "confidence": 0.64,
            "edge": 0.08,
            "recommended_stake": 2,
        },
    ]

    return preds 
