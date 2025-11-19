from __future__ import annotations
from typing import List, Dict, Any


class Optimizer:
    """
    FAZ-6 OPTIMIZER (FAZ-7 uyumlu mini çekirdek)
    -------------------------------------------
    Bu modülün görevi:
        - MLBrain tarafından üretilen tahminleri normalize etmek
        - Edge & Confidence güvenli sınırlar içine almak
        - Stake değerlerini stabil hale getirmek
        - FAZ-6 çekirdeğine uygun formata sokmak
    """

    def __init__(self) -> None:
        pass

    def _safe_float(self, v: Any, default: float = 0.0) -> float:
        try:
            return float(v)
        except:
            return default

    def optimize(self, preds: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Tahmin listesini optimize eder.
        """
        optimized: List[Dict[str, Any]] = []

        for p in preds:
            conf = self._safe_float(p.get("confidence", p.get("guven", 0.0)))
            edge = self._safe_float(p.get("edge", 0.0))

            # Güven normalize
            conf = max(0.50, min(conf, 0.85))

            # Edge stabilize
            edge = max(0.010, min(edge, 0.120))

            # Stake formülü
            stake = round(((conf - 0.50) * 3.4) + 0.75, 3)
            stake = max(0.65, min(stake, 3.0))

            q = dict(p)
            q["confidence"] = round(conf, 3)
            q["edge"] = round(edge, 3)
            q["stake"] = stake

            optimized.append(q)

        return optimized 
