# ================================================================
#                 FAZ-6 RISK MODÜLÜ
# ================================================================

from __future__ import annotations
from typing import Dict, Any, List

Prediction = Dict[str, Any]


def build_risk_predictions(memory: Dict[str, Any] | None) -> List[Prediction]:
    """
    FAZ-6 RISK modu için temel tahmin listesi.

    Mantık:
      - Güven (confidence) yüksek
      - Edge makul, aşırı agresif değil
      - risk_level: "low" / "medium"
    """
    preds: List[Prediction] = [
        {
            "id": "NBA:BOS@MIA",
            "league": "NBA",
            "match": "BOS@MIA",
            "market": "spread",
            "selection": "BOS -2.5",
            "confidence": 0.67,
            "edge": 0.045,
            "risk_level": "low",
        },
        {
            "id": "NBA:LAL@DEN",
            "league": "NBA",
            "match": "LAL@DEN",
            "market": "total",
            "selection": "UNDER 228.5",
            "confidence": 0.65,
            "edge": 0.04,
            "risk_level": "low",
        },
        {
            "id": "EL:FENER@OLY",
            "league": "EuroLeague",
            "match": "FENER@OLY",
            "market": "moneyline",
            "selection": "OLYMPIACOS",
            "confidence": 0.64,
            "edge": 0.05,
            "risk_level": "medium",
        },
        {
            "id": "EL:EFES@PART",
            "league": "EuroLeague",
            "match": "EFES@PART",
            "market": "spread",
            "selection": "PARTIZAN -3.5",
            "confidence": 0.63,
            "edge": 0.042,
            "risk_level": "medium",
        },
    ]

    # Hafızadan güvenli sayılabilecek seçimleri taşı (varsa)
    if memory:
        carry = memory.get("real_last") or memory.get("test_last") or []
        for p in carry:
            try:
                conf = float(p.get("confidence", 0.0))
                edge = float(p.get("edge", 0.0))
            except (TypeError, ValueError):
                continue

            # Sadece görece güvenli ve makul edge'li olanları ekle
            if conf >= 0.60 and edge >= 0.03:
                q = dict(p)
                q.setdefault("risk_level", "medium")
                q.setdefault("tag", "risk_memory_carry")
                preds.append(q)

    return preds
```0
