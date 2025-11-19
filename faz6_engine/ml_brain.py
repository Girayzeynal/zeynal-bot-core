from __future__ import annotations

from typing import Any, Dict, List, Optional

Prediction = Dict[str, Any]


class MLBrain:
    """
    FAZ-6 / FAZ-7 geçişi için güvenli çekirdek beyin.

    Amaç:
      - Harici modele bağlı olmadan çalışmak
      - Memory içindeki tahminleri normalize edip geri vermek
      - AutoEngine zinciri ile uyumlu olmak:
          MemoryUnit.load() -> MLBrain.predict() -> Optimizer -> Balance -> Core
    """

    def __init__(
        self,
        min_conf: float = 0.50,
        min_edge: float = 0.0,
    ) -> None:
        self.min_conf = min_conf
        self.min_edge = min_edge

    # ------------------------------
    #  İç yardımcılar
    # ------------------------------
    def _safe_float(self, v: Any, default: float = 0.0) -> float:
        try:
            if v is None:
                return default
            return float(v)
        except (TypeError, ValueError):
            return default

    def _extract_base_predictions(
        self,
        memory: Optional[Dict[str, Any]],
    ) -> List[Prediction]:
        """
        Memory içinden tahmin listesi çek.

        Desteklenen olası alanlar:
          - memory["predictions"]
          - memory["portfolio"]
          - memory["auto_last"]
          - memory["real_last"]
          - memory["test_last"]
        """
        if not isinstance(memory, dict):
            return []

        for key in (
            "predictions",
            "portfolio",
            "auto_last",
            "real_last",
            "test_last",
        ):
            val = memory.get(key)
            if isinstance(val, list):
                return [p for p in val if isinstance(p, dict)]

        return []

    # ------------------------------
    #  DIŞ API
    # ------------------------------
    def predict(
        self,
        memory: Optional[Dict[str, Any]],
    ) -> List[Prediction]:
        """
        AutoEngine tarafından çağrılan ana fonksiyon.

        Girdi:
          - memory: MemoryUnit.load() çıktısı (sözlük veya None)

        Çıktı:
          - normalize edilmiş prediction listesi
        """
        base = self._extract_base_predictions(memory)
        if not base:
            # Hafıza boşsa, beyin de sessiz çalışır.
            return []

        out: List[Prediction] = []

        for raw in base:
            p = dict(raw)

            conf = self._safe_float(
                p.get("confidence") or p.get("guven"),
                0.0,
            )
            edge = self._safe_float(
                p.get("edge"),
                0.0,
            )

            # Minimum güven ve edge filtresi
            if conf < self.min_conf:
                continue

            # Normalize alan isimleri
            p["confidence"] = conf
            p["edge"] = edge

            out.append(p)

        return out 
