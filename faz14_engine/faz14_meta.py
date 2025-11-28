# faz14_engine/faz14_meta.py

"""
FAZ-14 – META GAME ENGINE

Amaç:
- Prediction sinyalini (conf/edge/bucket) + FAZ-7.9 beyni +
  FAZ-11.5 extended feedback ile birleştirip
  "meta difficulty" ve "meta weight" üretmek.

Girdi:
- pred_signal: {
      "conf": float,
      "edge": float,
      "bucket": "LOW|MID|HIGH",
  }
- brain: faz79_brain() çıktısı
- feedback_state: build_extended_feedback_state() çıktısı

Çıktı:
- {
    "meta_difficulty": 0–1 (1 = çok zor maç),
    "meta_trust": 0–1.2,
    "final_weight": 0.3–1.7,
    "profile_hint": "SAFE|BAL|AGG",
    "notes": str,
  }
"""

from __future__ import annotations

from typing import Dict, Any


def _sf(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _normalize_bucket(b: str) -> str:
    b = (b or "").upper()
    if b in ("LOW", "MID", "HIGH"):
        return b
    return "MID"


def compute_meta_game_state(
    pred_signal: Dict[str, Any],
    brain: Dict[str, Any],
    feedback_state: Dict[str, Any],
) -> Dict[str, Any]:
    # ---- Güven / edge / bucket ----
    conf = _sf(pred_signal.get("conf", 0.6), 0.6)
    edge = _sf(pred_signal.get("edge", 0.03), 0.03)
    bucket = _normalize_bucket(pred_signal.get("bucket", "MID"))

    # ---- FAZ-7.9 ----
    brain_mode = str(brain.get("mode", "INIT"))
    vol = _sf(brain.get("vol", 0.10), 0.10)
    tci = _sf(brain.get("tci", 0.0), 0.0)
    noise = _sf(brain.get("noise_ratio", 0.4), 0.4)

    # ---- FAZ-11.5 ----
    trust_index = _sf(feedback_state.get("trust_index", 1.0), 1.0)
    risk_flag = str(feedback_state.get("risk_flag", "OK"))

    # ---------- META DIFFICULTY ----------
    # Basit model:
    #   - Volatilite ↑  ⇒ zorluk ↑
    #   - Noise ↑      ⇒ zorluk ↑
    #   - Conf & edge ↑ ⇒ zorluk ↓ (güçlü sinyal)
    raw_diff = 0.0
    raw_diff += min(1.0, vol * 3.0) * 0.40
    raw_diff += min(1.0, noise) * 0.35
    raw_diff += (1.0 - min(1.0, conf / 0.70)) * 0.15
    raw_diff += (0.05 - min(edge, 0.05)) * 8.0 * 0.10  # edge düşükse zorluk ↑

    meta_difficulty = max(0.0, min(1.0, raw_diff))

    # ---------- META TRUST ----------
    # Base: feedback trust_index + TCI
    meta_trust = trust_index * (0.6 + 0.4 * tci)
    # Bucket & brain mode tweak
    if bucket == "HIGH":
        meta_trust *= 0.95
    elif bucket == "LOW":
        meta_trust *= 1.05

    if brain_mode == "SAFE":
        meta_trust *= 1.05
    elif brain_mode == "AGG":
        meta_trust *= 0.97

    if risk_flag == "WARN":
        meta_trust *= 0.90
    elif risk_flag == "CRIT":
        meta_trust *= 0.75

    meta_trust = max(0.2, min(1.2, meta_trust))

    # ---------- FINAL WEIGHT ----------
    # Düşük zorluk & yüksek güven → weight ↑
    base_weight = (conf / 0.65) * (edge / 0.03)
    base_weight *= (1.1 - 0.6 * meta_difficulty)
    base_weight *= meta_trust

    final_weight = max(0.3, min(1.7, base_weight))

    # ---------- PROFILE HINT ----------
    if final_weight >= 1.3 and meta_difficulty < 0.45:
        profile = "AGG"
    elif final_weight <= 0.7 or meta_difficulty > 0.75:
        profile = "SAFE"
    else:
        profile = "BAL"

    notes = (
        f"mode={brain_mode}, bucket={bucket}, risk={risk_flag}, "
        f"vol={vol:.3f}, noise={noise:.3f}, trust={meta_trust:.3f}"
    )

    return {
        "meta_difficulty": round(meta_difficulty, 3),
        "meta_trust": round(meta_trust, 3),
        "final_weight": round(final_weight, 3),
        "profile_hint": profile,
        "notes": notes,
    }
