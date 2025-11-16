# ================================================================
#                 FAZ-6 EDGE MODÜLÜ
# ================================================================

from __future__ import annotations
from typing import List, Dict, Any


def build_edge_predictions(memory: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    """
    Edge odaklı portföy: daha yüksek edge kovalayan, risk iştahı yüksek seçimler.
    """
    return [
        {
            "id": "NBA:LAC@PHX",
            "league": "NBA",
            "market": "spread",
            "pick": "LAC +7.5",
            "confidence": 0.6,
            "edge": 0.085,
            "risk_level": "high",
            "notes": "Piyasa underdog'a düşük fiyat veriyor",
        },
        {
            "id": "NBA:DAL@HOU",
            "league": "NBA",
            "market": "total",
            "pick": "OVER 231.5",
            "confidence": 0.61,
            "edge": 0.09,
            "risk_level": "high",
            "notes": "Tempo + ofensif verim yüksek",
        },
        {
            "id": "EL:OLY@PART",
            "league": "EuroLeague",
            "market": "moneyline",
            "pick": "OLYMPIACOS",
            "confidence": 0.64,
            "edge": 0.08,
            "risk_level": "medium",
            "notes": "Match-up avantajı",
        },
    ] 
