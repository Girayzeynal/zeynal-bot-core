from typing import Dict, Any
from collections import deque

WINDOW = 50
_STATS: Dict[str, deque] = {}

def _k(league: str) -> str:
    return (league or "UNKNOWN").upper()

def push(league: str, rec: Dict[str, Any]) -> None:
    k = _k(league)
    if k not in _STATS:
        _STATS[k] = deque(maxlen=WINDOW)
    _STATS[k].append({
        "abs_error": rec.get("abs_error"),
        "hit_band": rec.get("hit_band"),
    })

def get_summary(league: str) -> Dict[str, float]:
    k = _k(league)
    dq = _STATS.get(k)
    if not dq:
        return {"n": 0, "hit_rate": 0.0, "mae": 0.0}

    n = 0
    hits = 0
    ae_sum = 0.0
    for r in dq:
        ae = r.get("abs_error")
        hb = r.get("hit_band")
        if ae is None or hb is None:
            continue
        n += 1
        ae_sum += float(ae)
        if hb:
            hits += 1

    if n == 0:
        return {"n": 0, "hit_rate": 0.0, "mae": 0.0}

    return {"n": n, "hit_rate": round(hits / n, 3), "mae": round(ae_sum / n, 2)}
