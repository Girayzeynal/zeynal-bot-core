# ================================================================
#                 FAZ-6 REAL-TIME MODÜLÜ
# ================================================================

from __future__ import annotations
from typing import List, Dict, Any


def build_real_predictions(memory: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    """
    Canlı / real-time odaklı portföy.
    Şu an için dummy; ileride live API verisi bağlanacak.
    """
    return [
        {
            "id": "LIVE:NBA:LAL@BOS",
            "league": "NBA",
            "market": "live_total",
            "pick": "OVER 219.5",
            "confidence": 0.62,
            "edge": 0.05,
            "risk_level": "medium",
            "notes": "3. çeyrek tempo yukarı",
        },
        {
            "id": "LIVE:EL:FENER@EFES",
            "league": "EuroLeague",
            "market": "live_spread",
            "pick": "FENER -2.5",
            "confidence": 0.65,
            "edge": 0.055,
            "risk_level": "medium",
            "notes": "Momentum Fener tarafında",
        },
    ] 
