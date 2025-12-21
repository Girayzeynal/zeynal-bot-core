from typing import Any, Dict

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
