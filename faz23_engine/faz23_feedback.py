# faz23_engine/faz23_feedback.py
from __future__ import annotations
import time
from typing import Any, Dict, List

from .faz23_datahub import memory_get, memory_put
from .faz23_stats import push as stats_push

# küçük adım ve sınırlar
W_STEP = 0.01
W_MIN = 0.00
W_MAX = 0.30
MIN_N = 10

# lig bazlı weights state (RAM)
_W: Dict[str, float] = {}

def _k(league: str) -> str:
    return (league or "UNKNOWN").upper()

def get_w_market(league: str) -> float:
    return float(_W.get(_k(league), 0.10))

def set_w_market(league: str, w: float) -> None:
    _W[_k(league)] = max(W_MIN, min(W_MAX, float(w)))

def _match_key(league: str, date_str: str, home: str, away: str) -> str:
    return f"{league}::{date_str}::{home}::{away}".upper()

def faz23_apply_result(
    *,
    league: str,
    date_str: str,
    home: str,
    away: str,
    actual_total: float,
) -> Dict[str, Any]:
    ts = int(time.time())
    key = _match_key(league, date_str, home, away)

    rec = memory_get(key)
    if not rec:
        return {"engine": "FAZ-23-FEEDBACK", "ts": ts, "error": "no_record", "tags": ["NO_RECORD"]}

    faz13 = rec.get("faz13", {}) if isinstance(rec.get("faz13"), dict) else {}
    faz22 = rec.get("faz22", {}) if isinstance(rec.get("faz22"), dict) else {}

    # meta_pred varsa onu, yoksa base_pred
    pred = None
    try:
        pred = float(faz22.get("meta_pred", faz13.get("base_pred")))
    except Exception:
        pred = None

    abs_err = round(abs(float(actual_total) - float(pred)), 2) if pred is not None else None

    # band hit
    hit_band = None
    band = faz13.get("band")
    if isinstance(band, list) and len(band) == 2:
        try:
            lo = float(band[0]); hi = float(band[1])
            hit_band = bool(lo <= float(actual_total) <= hi)
        except Exception:
            pass

    tags: List[str] = []
    if hit_band is True:
        tags.append("BAND_HIT")
    elif hit_band is False:
        tags.append("BAND_MISS")

    if abs_err is not None:
        if abs_err <= 6: tags.append("ERR_LOW")
        elif abs_err <= 12: tags.append("ERR_MID")
        else: tags.append("ERR_HIGH")

    # market etkisi: gerçek, market'e base'ten daha yakınsa +weight
    delta_hint = None
    try:
        base_pred = float(faz13.get("base_pred"))
        market_line = (faz22.get("market") or {}).get("line")
        if market_line is not None:
            market_line = float(market_line)
            d_base = abs(float(actual_total) - base_pred)
            d_mkt = abs(float(actual_total) - market_line)
            if d_mkt + 0.01 < d_base:
                delta_hint = "+market_weight"
                tags.append("MARKET_HELPED")
            elif d_base + 0.01 < d_mkt:
                delta_hint = "-market_weight"
                tags.append("MARKET_HURT")
    except Exception:
        pass

    # stats push
    stats_push(league, {"abs_error": abs_err, "hit_band": hit_band})

    # kontrollü öğrenme: yeterli örnek yoksa dokunma
    # (basit: memory içinde lig stat tutmuyorsak bile, en az 10 geri besleme sonrası aktif et)
    # burada rec içinde sayıyı tutabiliriz:
    cnt = int(rec.get("_fb_count", 0)) + 1
    rec["_fb_count"] = cnt

    if cnt >= MIN_N and delta_hint in ("+market_weight", "-market_weight"):
        w = get_w_market(league)
        if delta_hint == "+market_weight":
            set_w_market(league, w + W_STEP)
        else:
            set_w_market(league, w - W_STEP)
        tags.append("W_UPDATED")

    rec["actual_total"] = float(actual_total)
    rec["feedback"] = {
        "ts": ts,
        "pred_used": pred,
        "abs_error": abs_err,
        "hit_band": hit_band,
        "tags": tags,
        "delta_hint": delta_hint,
        "w_market": get_w_market(league),
        "fb_count": cnt,
    }
    memory_put(key, rec)

    return {"engine": "FAZ-23-FEEDBACK", "ts": ts, "error": None, "abs_error": abs_err, "hit_band": hit_band, "tags": tags} 
