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
            "pick": "LAC +7.5",
            "confidence": 0.60,
            "edge": 0.08,
            "risk_level": "medium",
        },
        {
            "id": "NBA:DAL@HOU",
            "league": "
