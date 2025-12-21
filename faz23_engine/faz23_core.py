import time
from typing import Any, Dict, Optional, List
from .faz23_datahub import memory_put

def _match_key(league: str, date_str: str, home: str, away: str) -> str:
    return f"{league}::{date_str}::{home}::{away}".upper()

def _tags(faz13: Dict[str, Any], faz22: Optional[Dict[str, Any]]) -> List[str]:
    tags: List[str] = []
    band = faz13.get("band")
    if isinstance(band, list) and len(band) == 2:
        try:
            width = float(band[1]) - float(band[0])
            if width > 18: tags.append("VAR_HIGH")
            if width < 8: tags.append("VAR_LOW")
        except Exception:
            pass
    if faz22 and isinstance(faz22, dict):
        conf = float(faz22.get("confidence", 0.0) or 0.0)
        if conf >= 0.8: tags.append("META_CONF_HIGH")
        if conf <= 0.55: tags.append("META_CONF_LOW")
    return tags

def faz23_memory_write(
    league: str,
    date_str: str,
    home: str,
    away: str,
    faz13_result: Dict[str, Any],
    faz22_result: Optional[Dict[str, Any]] = None,
    actual_total: Optional[float] = None,
) -> Dict[str, Any]:
    ts = int(time.time())
    key = _match_key(league, date_str, home, away)
    record = {
        "ts": ts,
        "key": key,
        "league": league,
        "date": date_str,
        "home": home,
        "away": away,
        "faz13": faz13_result,
        "faz22": faz22_result,
        "actual_total": actual_total,
        "tags": _tags(faz13_result, faz22_result),
    }
    stored = memory_put(key, record)
    return {"stored": bool(stored), "ts": ts, "engine": "FAZ-23-MEMORY"} 
