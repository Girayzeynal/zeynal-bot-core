# faz11_5_engine/faz11_5_extended.py

"""
FAZ-11.5 – EXTENDED FEEDBACK META ENGINE

Amaç:
- FAZ-11 summary + FAZ-7.9 beyni ile
  daha zengin meta state üretmek.
- FAZ-14 / 16 / 17 gibi GOD layer'lara
  tek bir "feedback_state" objesi sağlamak.

Girdi:
- f11_summary: faz11_last_summary() çıktısı (dict)
- brain: faz79_brain() çıktısı (dict) – opsiyonel

Çıktı:
- {
    "total": int,
    "correct": int,
    "daily_accuracy": float,
    "week_accuracy": float,
    "streak": int,
    "drift": float,
    "trust_index": float,
    "risk_flag": "OK|WARN|CRIT",
    "brain_mode": "SAFE|BAL|AGG|INIT",
    "brain_conf": float,
    "brain_edge": float,
  }
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, Optional


@dataclass
class FeedbackMeta:
    total: int = 0
    correct: int = 0
    daily_accuracy: float = 0.0
    week_accuracy: float = 0.0
    streak: int = 0
    drift: float = 0.0
    trust_index: float = 1.0
    risk_flag: str = "OK"
    brain_mode: str = "INIT"
    brain_conf: float = 0.0
    brain_edge: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "correct": self.correct,
            "daily_accuracy": round(self.daily_accuracy, 3),
            "week_accuracy": round(self.week_accuracy, 3),
            "streak": int(self.streak),
            "drift": round(self.drift, 4),
            "trust_index": round(self.trust_index, 3),
            "risk_flag": self.risk_flag,
            "brain_mode": self.brain_mode,
            "brain_conf": round(self.brain_conf, 3),
            "brain_edge": round(self.brain_edge, 3),
        }


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def build_extended_feedback_state(
    f11_summary: Dict[str, Any],
    brain: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    FAZ-11 summary + FAZ-7.9 brain -> zengin meta feedback state.
    """

    meta = FeedbackMeta()

    if not isinstance(f11_summary, dict):
        return meta.to_dict()

    # ---- FAZ-11 tarafı ----
    daily = f11_summary.get("daily", {}) or {}
    weekly = f11_summary.get("weekly", {}) or {}
    last = f11_summary.get("last", {}) or {}

    meta.total = _safe_int(daily.get("total", daily.get("count", 0)), 0)
    meta.correct = _safe_int(daily.get("correct", daily.get("hits", 0)), 0)
    meta.daily_accuracy = _safe_float(
        daily.get("accuracy", daily.get("daily_accuracy", 0.0)), 0.0
    )
    meta.week_accuracy = _safe_float(
        weekly.get("accuracy", weekly.get("week_accuracy", meta.daily_accuracy)), 
        meta.daily_accuracy,
    )
    meta.streak = _safe_int(last.get("streak", 0), 0)
    meta.drift = _safe_float(
        daily.get("model_drift", daily.get("drift", 0.0)), 0.0
    )

    # ---- Trust index hesabı ----
    # Basit ama iş görür:
    #   - accuracy yüksekse ↑
    #   - drift yüksekse ↓
    acc = meta.daily_accuracy
    week_acc = meta.week_accuracy
    drift = abs(meta.drift)

    base_trust = 0.5 * acc + 0.3 * week_acc + 0.2
    base_trust *= (1.0 - min(0.5, drift * 1.2))

    # 0.3–1.2 aralığına sıkıştır
    base_trust = max(0.3, min(1.2, base_trust))
    meta.trust_index = base_trust

    # ---- Risk flag ----
    if acc < 0.48 or drift > 0.12:
        meta.risk_flag = "CRIT"
    elif acc < 0.55 or drift > 0.07:
        meta.risk_flag = "WARN"
    else:
        meta.risk_flag = "OK"

    # ---- FAZ-7.9 brain entegrasyonu ----
    if isinstance(brain, dict):
        meta.brain_mode = str(brain.get("mode", "INIT"))
        meta.brain_conf = _safe_float(brain.get("conf", 0.0), 0.0)
        meta.brain_edge = _safe_float(brain.get("edge", 0.0), 0.0)

    return meta.to_dict()
