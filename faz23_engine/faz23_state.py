# faz23_engine/faz23_state.py
from __future__ import annotations

from typing import Dict, Any, Tuple, Optional
import time
import threading

# --- RAM-only DB (Fly free plan için) ---
_DB = {
    "predictions": {},  # match_id -> snapshot
    "leagues": {},      # league -> state
}
_LOCK = threading.Lock()

# agresif ama kontrollü (env yoksa default)
LR_BIAS = 0.18
LR_CONF = 0.10
WINDOW = 120

def _now() -> int:
    return int(time.time())

def _match_id(league: str, date_str: str, home: str, away: str) -> str:
    return f"{league}__{date_str}__{home}__{away}".lower()

def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def _league_state(league: str) -> Dict[str, Any]:
    st = _DB["leagues"].get(league)
    if not st:
        st = {
            "bias_total": 0.0,    # total score correction
            "conf_scale": 1.0,    # conf multiplier
            "conf_bias": 0.0,     # conf offset
            "history": [],        # rolling list
            "updated_at": _now(),
        }
        _DB["leagues"][league] = st
    return st

def faz23_apply_state(
    league: str,
    home: str,
    away: str,
    date_str: str,
    result: Dict[str, Any],
) -> None:
    """Called after /mac output is produced. Stores snapshot for later /result."""
    mid = _match_id(league, date_str, home, away)

    snap = {
        "league": league,
        "home": home,
        "away": away,
        "date_str": date_str,
        "ts": _now(),
        "base_pred": result.get("base_pred"),
        "band": result.get("band"),
        "confidence": result.get("confidence", 0.0),
        "market": result.get("market"),
    }

    with _LOCK:
        _DB["predictions"][mid] = snap

def faz23_record_result(
    league: str,
    home: str,
    away: str,
    date_str: str,
    home_score: int,
    away_score: int,
) -> Tuple[bool, str]:
    """User provides final score. Updates league calibration online."""
    mid = _match_id(league, date_str, home, away)
    actual_total = int(home_score) + int(away_score)

    with _LOCK:
        snap = _DB["predictions"].get(mid)
        if not snap:
            return False, "Bu maç için kayıtlı tahmin yok. Önce /mac çalıştır."

        base = snap.get("base_pred")
        if base is None:
            return False, "Snapshot base_pred yok. Öğrenme yapılamadı."

        base_f = float(base)
        band = snap.get("band")
        conf = float(snap.get("confidence", 0.0) or 0.0)

        err = float(actual_total) - base_f  # + ise gerçek daha yüksek

        # hit if inside band else |err| <= 7 fallback
        hit = None
        if isinstance(band, (list, tuple)) and len(band) == 2:
            try:
                lo, hi = float(band[0]), float(band[1])
                hit = (actual_total >= lo) and (actual_total <= hi)
            except Exception:
                hit = None
        if hit is None:
            hit = (abs(err) <= 7.0)

        st = _league_state(league)

        # 1) bias_total update
        st["bias_total"] = float(st.get("bias_total", 0.0)) + LR_BIAS * err
        st["bias_total"] = _clamp(st["bias_total"], -25.0, 25.0)

        # 2) confidence calibration update
        target = 1.0 if hit else 0.0
        conf_scale = float(st.get("conf_scale", 1.0))
        conf_bias = float(st.get("conf_bias", 0.0))

        calibrated = _clamp(conf * conf_scale + conf_bias, 0.0, 1.0)
        delta = (target - calibrated)

        conf_scale = conf_scale + (LR_CONF * delta) * 0.6
        conf_bias = conf_bias + (LR_CONF * delta) * 0.4

        st["conf_scale"] = _clamp(conf_scale, 0.6, 1.4)
        st["conf_bias"] = _clamp(conf_bias, -0.25, 0.25)

        # 3) rolling history
        hist = st.get("history", [])
        hist.append({
            "ts": _now(),
            "mid": mid,
            "actual_total": actual_total,
            "base_pred": base_f,
            "err": err,
            "hit": bool(hit),
            "conf": conf,
        })
        if len(hist) > WINDOW:
            hist = hist[-WINDOW:]
        st["history"] = hist
        st["updated_at"] = _now()

        # attach result into snapshot (optional)
        snap["result"] = {"home": home_score, "away": away_score, "total": actual_total}
        _DB["predictions"][mid] = snap

        # compute simple diagnostics
        hit_rate = sum(1 for x in hist if x["hit"]) / max(1, len(hist))
        err_ma = sum(x["err"] for x in hist) / max(1, len(hist))

    msg = (
        f"✅ FAZ-23 öğrenme işlendi\n"
        f"{league} | {date_str} | {home}-{away}\n"
        f"Gerçek toplam: {actual_total}\n"
        f"Base: {base_f:.1f} | Hata: {err:+.1f} | Hit: {hit}\n"
        f"bias_total: {st['bias_total']:+.2f}\n"
        f"conf_scale: {st['conf_scale']:.3f} | conf_bias: {st['conf_bias']:+.3f}\n"
        f"hit_rate({len(hist)}): {hit_rate:.2f} | err_ma: {err_ma:+.2f}\n"
        f"Not: Fly free → RAM öğrenme (restart olursa sıfırlanır)"
    )
    return True, msg

def faz23_get_league_calibration(league: str) -> Dict[str, float]:
    """FAZ-22 will call this to apply learned corrections."""
    with _LOCK:
        st = _league_state(league)
        return {
            "bias_total": float(st.get("bias_total", 0.0)),
            "conf_scale": float(st.get("conf_scale", 1.0)),
            "conf_bias": float(st.get("conf_bias", 0.0)),
        }
