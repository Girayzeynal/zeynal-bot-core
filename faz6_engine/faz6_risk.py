# ================================================================
#                 FAZ-6 RISK MODÜLÜ
# ================================================================

from __future__ import annotations
from typing import List, Dict, Any


def build_risk_predictions(memory: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    """
    Risk odaklı portföy: daha yüksek güven, nispeten düşük edge yeterli.
    Hafızadan gelen loss_streak'e göre daha konservatif olabilir.
    """
    loss_streak = int((memory or {}).get("loss_streak", 0))

    base_conf = 0.7
    if loss_streak > 0:
        base_conf += min(0.05, loss_streak * 0.01)

    return [
        {
            "id": "NBA:MIA@NYK",
            "league": "NBA",
            "market": "moneyline",
            "pick": "NYK",
            "confidence": min(0.9, base_conf + 0.04),
            "edge": 0.035,
            "risk_level": "low",
            "notes": "Ev avantajı, risk modu",
        },
        {
            "id": "NBA:CHI@MIL",
            "league": "NBA",
            "market": "spread",
            "pick": "MIL -6.5",
            "confidence": min(0.9, base_conf + 0.02),
            "edge": 0.03,
            "risk_level": "low",
            "notes": "Güç farkı, kontrollü",
        },
        {
            "id": "EL:REAL@BARCA",
            "league": "EuroLeague",
            "market": "total",
            "pick": "UNDER 162.5",
            "confidence": base_conf,
            "edge": 0.028,
            "risk_level": "medium",
            "notes": "Tempo düşük senaryo",
        },
    ] 
