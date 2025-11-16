# ================================================================
#                    FAZ-6 HAFIZA MODÜLÜ
# ================================================================

from __future__ import annotations
import json
import os
from typing import Dict, Any

_DEFAULT_MEMORY_FILE = os.getenv(
    "FAZ6_MEMORY_PATH",
    os.path.join(os.path.dirname(__file__), "faz6_memory.json"),
)


def load_memory() -> Dict[str, Any]:
    """
    Yerel JSON dosyadan hafıza yükler.
    Dosya yoksa boş dict döner.
    """
    try:
        if not os.path.exists(_DEFAULT_MEMORY_FILE):
            return {}
        with open(_DEFAULT_MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            return {}
    except Exception:
        # Hafıza hatalıysa sistem çalışsın diye boş dict döneriz.
        return {}


def save_memory(update: Dict[str, Any]) -> None:
    """
    Hafızaya incremental yazım.
    Eski veriyi okur, günceller, geri yazar.
    """
    try:
        current = load_memory()
        current.update(update)
        with open(_DEFAULT_MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
    except Exception:
        # Hafıza yazım hatası sistemi durdurmasın
        pass 
