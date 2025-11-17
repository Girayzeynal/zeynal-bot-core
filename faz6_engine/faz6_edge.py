"""
FAZ-6 EDGE MODE
Yüksek edge fırsatlarını hedefler.
Risk artar ama potansiyel kazanç da artar.
"""

from __future__ import annotations
from typing import List, Dict, Any


def build_edge_predictions(memory: Dict[str, Any] | None) -> List[Dict[str, Any]]:
    return [
        {
            "id": "EDGE-1",
            "market": "player_points",
            "pick": "OVER 22.5",
            "edge": 0.11,
            "confidence": 0.63,
            "league": "NBA",
        },
        {
            "id": "EDGE-2",
            "market": "match_winner",
            "pick": "AWAY",
            "edge": 0.14,
            "confidence": 0.61,
            "league": "TURKEY-BSL",
        }
    ]
