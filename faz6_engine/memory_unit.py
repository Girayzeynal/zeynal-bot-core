from __future__ import annotations

import json
from typing import Any, Dict, Optional, List


class MemoryUnit:
    """
    FAZ-6 Bellek Modülü (FAZ-7 uyumlu)
    -----------------------------------
    Amaç:
        - AutoEngine zincirinde hafıza okuma / yazma görevini üstlenir.
        - JSON tabanlı hafıza tutar.
        - Kırılma yaşanmaması için ultra güvenli try/except blokları içerir.

    Kullanım zinciri:
        last = memory.load()
        new_preds = brain.predict(last)
        optimized = optimizer.optimize(new_preds)
        balanced = balance.rebalance(optimized)
        final = core.process(balanced)
        memory.save(final)
    """

    MEMORY_FILE = "faz6_memory.json"

    def __init__(self) -> None:
        pass

    # --------------------------------
    #  Güvenli float helper
    # --------------------------------
    def _safe_float(self, v: Any, default: float = 0.0) -> float:
        try:
            if v is None:
                return default
            return float(v)
        except (TypeError, ValueError):
            return default

    # --------------------------------
    #  LOAD
    # --------------------------------
    def load(self) -> Dict[str, Any]:
        """
        Belleği JSON dosyasından yükler.
        Dosya yoksa boş hafıza döner.
        """
        try:
            with open(self.MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except FileNotFoundError:
            return {}
        except Exception:
            return {}

        return {}

    # --------------------------------
    #  SAVE
    # --------------------------------
    def save(self, result: Dict[str, Any]) -> bool:
        """
        Son prediction setini hafızaya kaydeder.
        result → AutoEngine final çıktısıdır.
        """
        try:
            if not isinstance(result, dict):
                return False

            preds = result.get("predictions") or result.get("portfolio") or []

            mem = {
                "predictions": preds,
                "portfolio": preds,
                "auto_last": preds,
            }

            with open(self.MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump(mem, f, indent=2, ensure_ascii=False)

            return True

        except Exception:
            return False 
