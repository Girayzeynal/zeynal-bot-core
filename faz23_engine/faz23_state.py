# faz23_engine/faz23_state.py

from __future__ import annotations
from typing import Dict, Any, Optional, Tuple
import os, json, time, threading

_LOCK = threading.Lock()

DEFAULT_STORE = os.getenv("FAZ23_STORE_PATH", "/data/faz23_store.json")
# Fly'da /data volume yoksa fallback:
if not os.path.isdir(os.path.dirname(DEFAULT_STORE)):
    DEFAULT_STORE = os.getenv("FAZ23_STORE_PATH", "/tmp/faz23_store.json")

LR_BIAS = float(os.getenv("FAZ23_LR_BIAS", "0.08"))          # bias learning rate
LR_CONF = float(os.getenv("FAZ23_LR_CONF", "0.05"))          # confidence calibration rate
WINDOW = int(os.getenv("FAZ23_WINDOW", "80"))                # rolling window size (per league)


def _now() -> int:
    return int(time.time())


def _load() -> Dict[str, Any]:
    if not os.path.exists(DEFAULT_STORE):
        return {"predictions": {}, "leagues": {}}
    try:
        with open(DEFAULT_STORE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"predictions": {}, "leagues": {}}


def _save(db: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(DEFAULT_STORE), exist_ok=True)
    tmp = DEFAULT_STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False)
    os.replace(tmp, DEFAULT_STORE)


def _match_id(league: str, date_str: str, home: str, away: str) -> str:
    # stable key
    return f"{league}__{date_str}__{home}__{away}".lower()


def _get_league_state(db: Dict[str, Any], league: str) -> Dict[str, Any]:
    leagues = db.setdefault("leagues", {})
    st = leagues.get(league)
    if not st:
        st = {
            "bias_total": 0.0,          # learned additive correction to total
            "conf_scale": 1.0,          # multiplicative scaling for confidence
            "conf_bias": 0.0,           # additive offset for confidence
            "history": [],              # rolling outcomes
            "updated_at": _now(),
        }
        leagues[league] = st
    return st


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def faz23_apply_state(
    league: str,
    home: str,
    away: str,
    date_str: str,
    result: Dict[str, Any],
) -> None:
    """
    Called after a prediction is produced.
    Stores a prediction snapshot so later we can attach the real result and learn.
    """
    mid = _match_id(league, date_str, home, away)

    base = result.get("base_pred")
    band = result.get("band")
    confidence = result.get("confidence")

    # Minimal fields needed for learning
    snap = {
        "league": league,
        "home": home,
        "away": away,
        "date_str": date_str,
        "ts": _now(),
        "base_pred": base,
        "band": band,
        "confidence": confidence,
        "market": result.get("market"),
    }

    with _LOCK:
        db = _load()
        db.setdefault("predictions", {})[mid] = snap
        _save(db)


def faz23_record_result(
    league: str,
    home: str,
    away: str,
    date_str: str,
    home_score: int,
    away_score: int,
) -> Tuple[bool, str]:
    """
    Called when user inputs final score.
    Learns: updates league bias and confidence calibration based on error.
    """
    mid = _match_id(league, date_str, home, away)
    actual_total = int(home_score) + int(away_score)

    with _LOCK:
        db = _load()
        preds = db.setdefault("predictions", {})
        snap = preds.get(mid)

        if not snap:
            return False, "Bu maç için kayıtlı tahmin bulunamadı (önce /mac çalıştırılmış olmalı)."

        base = snap.get("base_pred")
        conf = snap.get("confidence", 0.0)
        band = snap.get("band")

        if base is None:
            return False, "Tahmin snapshot'ında base_pred yok, öğrenme yapılamadı."

        base_f = float(base)
        err = float(actual_total) - base_f  # + ise gerçek daha yüksek

        # League state
        st = _get_league_state(db, league)

        # --- 1) Bias learning (total correction) ---
        # Update bias toward reducing future error: new_base = base + bias_total
        st["bias_total"] = float(st.get("bias_total", 0.0)) + (LR_BIAS * err)
        st["bias_total"] = _clamp(st["bias_total"], -25.0, 25.0)

        # --- 2) Confidence calibration ---
        # "hit" if actual is inside band (if band exists), else use |err| threshold
        hit = None
        if isinstance(band, (list, tuple)) and len(band) == 2:
            try:
                lo, hi = float(band[0]), float(band[1])
                hit = (actual_total >= lo) and (actual_total <= hi)
            except Exception:
                hit = None
        if hit is None:
            hit = (abs(err) <= 7.0)  # fallback

        # Convert hit into a target confidence adjustment
        # if hit, slightly boost; if miss, slightly reduce
        target = 1.0 if hit else 0.0
        conf_f = float(conf or 0.0)
        conf_scale = float(st.get("conf_scale", 1.0))
        conf_bias = float(st.get("conf_bias", 0.0))

        # Online update: nudges scale/bias so calibrated_conf moves toward target
        calibrated = _clamp(conf_f * conf_scale + conf_bias, 0.0, 1.0)
        delta = (target - calibrated)

        conf_scale = conf_scale + (LR_CONF * delta) * 0.6
        conf_bias = conf_bias + (LR_CONF * delta) * 0.4

        st["conf_scale"] = _clamp(conf_scale, 0.6, 1.4)
        st["conf_bias"] = _clamp(conf_bias, -0.25, 0.25)

        # --- 3) Rolling history ---
        hist = st.get("history", [])
        hist.append({
            "mid": mid,
            "ts": _now(),
            "actual_total": actual_total,
            "base_pred": base_f,
            "err": err,
            "hit": bool(hit),
            "conf": conf_f,
        })
        if len(hist) > WINDOW:
            hist = hist[-WINDOW:]
        st["history"] = hist
        st["updated_at"] = _now()

        # Save & keep prediction with result attached
        snap["result"] = {"home": home_score, "away": away_score, "total": actual_total}
        preds[mid] = snap
        _save(db)

    msg = (
        f"✅ FAZ-23 öğrenme işlendi\n"
        f"Maç: {home}-{away} ({league} | {date_str})\n"
        f"Gerçek toplam: {actual_total}\n"
        f"Base: {base_f:.1f} | Hata: {err:+.1f}\n"
        f"Hit: {hit}\n"
        f"Yeni bias_total: {st['bias_total']:+.2f}\n"
        f"conf_scale: {st['conf_scale']:.3f} | conf_bias: {st['conf_bias']:+.3f}"
    )
    return True, msg


def faz23_get_league_calibration(league: str) -> Dict[str, float]:
    """
    Used by FAZ-22 to calibrate outputs.
    """
    with _LOCK:
        db = _load()
        st = _get_league_state(db, league)
        return {
            "bias_total": float(st.get("bias_total", 0.0)),
            "conf_scale": float(st.get("conf_scale", 1.0)),
            "conf_bias": float(st.get("conf_bias", 0.0)),
        }
