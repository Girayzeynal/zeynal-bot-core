from __future__ import annotations
from typing import Dict, Any

import json
import os
from pathlib import Path

_MEMORY_PATH = Path(__file__).with_name("faz6_memory.json")
_CACHE: Dict[str, Any] | None = None


def _load_from_disk() -> Dict[str, Any]:
    if not _MEMORY_PATH.exists():
        return {}
    try:
        with _MEMORY_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        return {}
    return {}


def _save_to_disk(data: Dict[str, Any]) -> None:
    try:
        with _MEMORY_PATH.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        # Disk yoksa sessizce geç
        pass


def load_memory() -> Dict[str, Any]:
    global _CACHE
    if _CACHE is None:
        _CACHE = _load_from_disk()
    return dict(_CACHE)


def save_memory(update: Dict[str, Any]) -> None:
    global _CACHE
    base = load_memory()
    base.update(update)
    _CACHE = base
    _save_to_disk(base)
