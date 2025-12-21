# faz23_engine/faz23_feedback.py
import time
from typing import Any, Dict, List

from .faz23_datahub import memory_get, memory_put
from .faz23_stats import push as stats_push


def _match_key(league: str, date_str: str, home: str, away: str) -> str:
    return f"{league}::{date_str}::{home}::{away}".upper()


def faz23_apply_result(
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
        return {
            "engine": "FAZ-23-FEEDBACK",
            "ts": ts,
            "key": key,
            "error": "no_memory_record",
            "tags": ["NO_RECORD"],
            "abs_error": None,
            "hit_band": None,
            "meta_delta_hint": None,
            "new_weights": None,
        }

    faz13 = rec.get("faz13", {}) if isinstance(rec.get("faz13"), dict) else {}
    faz22 = rec.get("faz22", {}) if isinstance(rec.get("faz22"), dict) else None

    # Kullanılan tahmin
    pred = None
    try:
        pred = float((faz22 or {}).get("meta_pred", faz13.get("base_pred")))
    except Exception:
        pred = None

    abs_err = round(abs(float(actual_total) - float(pred)), 2) if pred is not None else None

    hit_band = None
    tags: List[str] = []
    band = faz13.get("band")
    if isinstance(band, list) and len(band) == 2:
        try:
            lo, hi = float(band[0]), float(band[1])
            hit_band = lo <= float(actual_total) <= hi
            tags.append("BAND_HIT" if hit_band else "BAND_MISS")
        except Exception:
            pass

    if abs_err is not None:
        if abs_err <= 6:
            tags.append("ERR_LOW")
        elif abs_err <= 12:
            tags.append("ERR_MID")
        else:
            tags.append("ERR_HIGH")

    # Market etkisi analizi
    meta_delta_hint = None
    try:
        base_pred = float(faz13.get("base_pred"))
        market_line = float((faz13.get("market") or {}).get("totals_line"))
        d_base = abs(float(actual_total) - base_pred)
        d_mkt = abs(float(actual_total) - market_line)
        if d_mkt + 0.01 < d_base:
            meta_delta_hint = "+market_weight"
            tags.append("MARKET_HELPED")
        elif d_base + 0.01 < d_mkt:
            meta_delta_hint = "-market_weight"
            tags.append("MARKET_HURT")
    except Exception:
        pass

    # ✅ CRITICAL FIX: faz22_apply_hint geç yükleniyor (circular kırıldı)
    new_weights = None
    if meta_delta_hint in ("+market_weight", "-market_weight"):
        try:
            from faz22_engine import faz22_apply_hint  # LAZY IMPORT
            new_weights = faz22_apply_hint(league, meta_delta_hint)
            tags.append("FAZ22_WEIGHTS_UPDATED")
        except Exception as e:
            tags.append(f"FAZ22_WEIGHT_UPDATE_FAIL:{e}")

    # Stats güncelle
    stats_push(league, {"abs_error": abs_err, "hit_band": hit_band})

    rec["actual_total"] = float(actual_total)
    rec["feedback"] = {
        "ts": ts,
        "pred_used": pred,
        "abs_error": abs_err,
        "hit_band": hit_band,
        "tags": tags,
        "meta_delta_hint": meta_delta_hint,
        "new_weights": new_weights,
    }
    memory_put(key, rec)

    return {
        "engine": "FAZ-23-FEEDBACK",
        "ts": ts,
        "key": key,
        "error": None,
        "tags": tags,
        "abs_error": abs_err,
        "hit_band": hit_band,
        "meta_delta_hint": meta_delta_hint,
        "new_weights": new_weights,
    } 
