# ================================================================
#                 FAZ-6 MEMORY UNIT (BASİT)
# ================================================================

from __future__ import annotations
from typing import Dict, Any
import json
import os

MEMORY_FILE = "faz6_memory.json"


def load_memory() -> Dict[str, Any]:
    """
    Basit JSON tabanlı hafıza.
    Dosya yoksa veya bozuksa boş dict döner.
    """
    if not os.path.exists(MEMORY_FILE):
        return {}
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_memory(data: Dict[str, Any]) -> None:
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        # Fly.io ephemeral disk veya izin sorunlarında sessiz geç
        pass
