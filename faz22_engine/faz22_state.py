from typing import Dict, Any
import time

_STATE: Dict[str, Dict[str, Any]] = {}

DEFAULTS = {
    "w17": 0.15,
    "step": 0.02,
    "w17_min": 0.00,
    "w17_max": 0.30,
}

def _league_key(league: str) -> str:
    return (league or "UNKNOWN").upper()

def get_weights(league: str) -> Dict[str, float]:
    k = _league_key(league)
    s = _STATE.get(k, {})
    w17 = float(s.get("w17", DEFAULTS["w17"]))
    w17 = max(DEFAULTS["w17_min"], min(DEFAULTS["w17_max"], w17))
    w13 = 1.0 - w17
    _STATE[k] = {"w13": w13, "w17": w17, "ts": int(time.time())}
    return {"w13": w13, "w17": w17}

def apply_hint(league: str, hint: str | None) -> Dict[str, float]:
    cur = get_weights(league)
    w17 = float(cur["w17"])
    step = DEFAULTS["step"]
    if hint == "+market_weight":
        w17 += step
    elif hint == "-market_weight":
        w17 -= step
    w17 = max(DEFAULTS["w17_min"], min(DEFAULTS["w17_max"], w17))
    w13 = 1.0 - w17
    _STATE[_league_key(league)] = {"w13": w13, "w17": w17, "ts": int(time.time())}
    return {"w13": w13, "w17": w17}
