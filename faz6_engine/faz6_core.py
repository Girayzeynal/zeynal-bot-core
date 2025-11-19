from __future__ import annotations
from typing import Dict, Any, List


class Faz6Core:
    """
    FAZ-6 ANA ÇEKİRDEK
    ------------------
    Auto Engine → MLBrain → Optimizer → Faz6Core → Balance Engine
    zincirinde 'final karar + çıktıyı' oluşturan katman.

    Görev:
        - Optimizasyon sonrası tahminleri işlemek
        - Risk katsayılarını uygulamak
        - FAZ-6 formatında final paket döndürmek
    """

    def __init__(self) -> None:
        pass

    def _safe_float(self, v: Any, default: float = 0.0) -> float:
        try:
            return float(v)
        except:
            return default

    def process(self, preds: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Optimize edilmiş tahminleri alır (Optimizer çıkışı)
        FAZ-6 risk/rating hesaplamalarını uygular.
        """
        final_list: List[Dict[str, Any]] = []

        for p in preds:
            conf = self._safe_float(p.get("confidence", 0.0))
            edge = self._safe_float(p.get("edge", 0.0))
            stake = self._safe_float(p.get("stake", 0.0))

            # FAZ-6 rating formülü
            rating = round((conf * 0.60) + (edge * 3.0) + (stake * 0.13), 3)
            rating = max(0.10, min(rating, 1.00))

            q = dict(p)
            q["rating"] = rating
            q["risk"] = round(1.0 - conf, 3)
            q["faz6_tag"] = "FAZ6_CORE_OK"

            final_list.append(q)

        return final_list 
