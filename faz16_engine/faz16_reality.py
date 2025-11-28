# faz16_engine/faz16_reality.py

"""
FAZ-16 – REALITY CORRECTION LOOP

Amaç:
- Gerçek sonuçlar + FAZ-11/11.5 performansı + FAZ-7.9 beyni ile
  prediction sinyallerine "realite düzeltme" faktörü üretmek.

Kullanım:
- rc_state = compute_reality_state(brain, feedback_state)
- corrected = apply_reality_correction(pred_signal, rc_state)
"""

from __future__ import annotations

from typing import Dict, Any


def _sf(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def compute_reality_state(
    brain: Dict[str, Any],
    feedback_state: Dict[str, Any],
) -> Dict[str, Any]:
    mode = str(brain.get("mode", "INIT"))
    conf = _sf(brain.get("conf", 0.0), 0.0)
    edge = _sf(brain.get("edge", 0.0), 0.0)
    vol = _sf(brain.get("vol", 0.0), 0.0)

    daily_acc = _sf(feedback_state.get("daily_accuracy", 0.0), 0.0)
    drift = _sf(feedback_state.get("drift", 0.0), 0.0)
    trust = _sf(feedback_state.get("trust_index", 1.0), 1.0)
    risk = str(feedback_state.get("risk_flag", "OK"))

    # Conf düzeltme faktörü
    conf_factor = 1.0
    edge_factor = 1.0

    # Performans düşükse sinyali kısmak
    if daily_acc < 0.48 or risk == "CRIT":
        conf_factor *= 0.88
        edge_factor *= 0.90
    elif daily_acc < 0.55 or risk == "WARN":
        conf_factor *= 0.94
        edge_factor *= 0.95

    # Drift yüksekse
    d = abs(drift)
    if d > 0.12:
        conf_factor *= 0.90
        edge_factor *= 0.92
    elif d > 0.07:
        conf_factor *= 0.95
        edge_factor *= 0.96

    # Güven / edge zaten çok yüksekse hafif kırp
    if conf > 0.70:
        conf_factor *= 0.97
    if edge > 0.05:
        edge_factor *= 0.97

    # Volatilite yüksekse riski azalt
    if vol > 0.18:
        conf_factor *= 0.94
        edge_factor *= 0.92

    # Trust yüksekse bir miktar geri aç
    conf_factor *= (0.9 + 0.2 * min(trust, 1.1))
    edge_factor *= (0.9 + 0.2 * min(trust, 1.1))

    conf_factor = max(0.65, min(1.10, conf_factor))
    edge_factor = max(0.65, min(1.12, edge_factor))

    return {
        "mode": mode,
        "conf_factor": round(conf_factor, 3),
        "edge_factor": round(edge_factor, 3),
        "vol": round(vol, 3),
        "daily_accuracy": round(daily_acc, 3),
        "drift": round(drift, 4),
        "trust_index": round(trust, 3),
        "risk_flag": risk,
    }


def apply_reality_correction(
    pred_signal: Dict[str, Any],
    rc_state: Dict[str, Any],
) -> Dict[str, Any]:
    conf = _sf(pred_signal.get("conf", 0.6), 0.6)
    edge = _sf(pred_signal.get("edge", 0.03), 0.03)
    stake = _sf(pred_signal.get("stake", 1.0), 1.0)

    cf = _sf(rc_state.get("conf_factor", 1.0), 1.0)
    ef = _sf(rc_state.get("edge_factor", 1.0), 1.0)

    new_conf = max(0.0, min(0.99, conf * cf))
    new_edge = max(0.0, edge * ef)

    # Stake'i de hafif düzeltelim
    stake_factor = (cf + ef) / 2.0
    new_stake = max(0.10, stake * stake_factor)

    out = dict(pred_signal)
    out["conf"] = round(new_conf, 3)
    out["edge"] = round(new_edge, 3)
    out["stake"] = round(new_stake, 2)
    out["faz16_state"] = rc_state

    return out
