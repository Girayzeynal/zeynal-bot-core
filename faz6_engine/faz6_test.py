# ================================================================
#                 FAZ-6 TEST MODÜLÜ
# ================================================================

from __future__ import annotations
from typing import List, Dict, Any


def build_test_predictions(memory: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    """
    Statik test datası – sistemin formatını doğrulamak için.
    """
    return [
        {
            "id": "NBA:LAL@BOS",
            "league": "NBA",
            "market": "total",
            "pick": "OVER 225.5",
            "confidence": 0.68,
            "edge": 0.06,
            "risk_level": "medium",
            "notes": "Test veri - 1",
        },
        {
            "id": "NBA:GSW@DEN",
            "league": "NBA",
            "market": "spread",
            "pick": "GSW +4.5",
            "confidence": 0.63,
            "edge": 0.045,
            "risk_level": "low",
            "notes": "Test veri - 2",
        },
        {
            "id": "EL:FENER@EFES",
            "league": "EuroLeague",
            "market": "moneyline",
            "pick": "FENER",
            "confidence": 0.71,
            "edge": 0.075,
            "risk_level": "medium",
            "notes": "Test veri - 3",
        },
    ] 
