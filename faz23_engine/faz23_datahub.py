# faz23_engine/faz23_datahub.py
from __future__ import annotations

from typing import Any, Dict

# Fly.io free tier: in-memory küçük cache (persist değil).
# İstersen sonra volume/redis ile kalıcı yaparız.
_MEM: Dict[str, Dict[str, Any]] = {}


def memory_put(key: str, payload: Dict[str, Any]) -> bool:
    try:
        _MEM[key] = payload
        return True
    except Exception:
        return False


def memory_get(key: str) -> Dict[str, Any]:
    return _MEM.get(key, {})


def memory_size() -> int:
    return len(_MEM)
