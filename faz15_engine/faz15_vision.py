# faz15_engine/faz15_vision.py

"""
FAZ-15 – DEEP BEHAVIORAL VISION ENGINE

Amaç:
- OCR meta + skor/tempo benzeri bilgilerden
  görsel tabanlı davranış sinyali çıkarmak.

Girdi (önerilen):
- visual_meta: {
      "home_score": int,
      "away_score": int,
      "period": int,
      "clock_ratio": 0–1 (maçta ne kadar süre geçti),
      "total_line": float (varsa),
      "live_total": float (varsa),
  }
- ocr_meta: ultra_ocr_engine_v3 meta alanı (engine, classifier, score vs.)

Çıktı:
- {
    "tempo_bias": -0.3..+0.3,
    "score_bias": -0.3..+0.3,
    "visual_trust": 0–1,
    "label": "UNDERLEAN|OVERLEAN|NEUTRAL",
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


def _si(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def compute_visual_behavior(
    visual_meta: Dict[str, Any],
    ocr_meta: Dict[str, Any],
) -> Dict[str, Any]:
    home = _si(visual_meta.get("home_score", 0))
    away = _si(visual_meta.get("away_score", 0))
    total_line = _sf(visual_meta.get("total_line", 0.0), 0.0)
    live_total = _sf(visual_meta.get("live_total", 0.0), 0.0)
    clock_ratio = max(0.0, min(1.0, _sf(visual_meta.get("clock_ratio", 0.5), 0.5)))

    score_sum = home + away

    # OCR güvenini meta'dan çek
    ocr_score = _sf(ocr_meta.get("prob_score", 0.5), 0.5)
    raw_conf = _sf(ocr_meta.get("raw_confidence", 0.5), 0.5)

    # Visual trust: OCR kalitesi + saat oranı
    visual_trust = 0.5 * ocr_score + 0.3 * raw_conf + 0.2 * clock_ratio
    visual_trust = max(0.0, min(1.0, visual_trust))

    # Tempo / score bias
    tempo_bias = 0.0
    score_bias = 0.0
    label = "NEUTRAL"

    if total_line > 0 and clock_ratio > 0.15:
        # Basit pace tahmini: current_score / elapsed
        pace_total = score_sum / max(clock_ratio, 0.05)
        pace_ratio = pace_total / total_line  # 1.0 civarı normal

        # 0.8–1.2 bandı etrafında değerlendir
        tempo_bias = (pace_ratio - 1.0) * 0.6
        tempo_bias = max(-0.3, min(0.3, tempo_bias))

        if live_total > 0:
            price_delta = (live_total - total_line) / total_line
            score_bias = price_delta * 1.1
            score_bias = max(-0.3, min(0.3, score_bias))

        if tempo_bias > 0.08 or score_bias > 0.08:
            label = "OVERLEAN"
        elif tempo_bias < -0.08 or score_bias < -0.08:
            label = "UNDERLEAN"
        else:
            label = "NEUTRAL"

    notes = (
        f"score={home}-{away} (sum={score_sum}), line={total_line}, "
        f"clock_ratio={clock_ratio:.2f}, ocr_score={ocr_score:.2f}"
    )

    return {
        "tempo_bias": round(tempo_bias, 3),
        "score_bias": round(score_bias, 3),
        "visual_trust": round(visual_trust, 3),
        "label": label,
        "notes": notes,
    }
