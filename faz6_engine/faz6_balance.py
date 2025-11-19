from __future__ import annotations
from typing import List, Dict, Any


class BalanceEngine:
    """
    FAZ-6 BALANCE ENGINE
    --------------------
    AutoEngine → CoreEngine sonrası çıkan tahminleri
    kupon mantığı için yeniden dengeler.
    """

    def __init__(self):
        pass

    def balance(self, predictions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Basit ama FAZ-6 uyumlu bir dengeleme formülü.
        """
        if not predictions:
            return []

        preds = list(predictions)

        # Güven + Edge + Rating → final sıralama
        preds.sort(
            key=lambda x: (
                float(x.get("rating", 0.0)),
                float(x.get("confidence", 0.0)),
                float(x.get("edge", 0.0)),
            ),
            reverse=True,
        )

        # Basit stake normalizasyonu
        for p in preds:
            conf = float(p.get("confidence", 0.0))
            edge = float(p.get("edge", 0.0))
            p["final_stake"] = round((conf * 0.5) + (edge * 2.0), 3)

        return preds 
