from __future__ import annotations

from typing import Any, Dict, List

from .presets import ModePreset

Prediction = Dict[str, Any]


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def score_prediction(p: Prediction) -> float:
    """
    Basit skor fonksiyonu:
      - confidence %60 ağırlık
      - edge %40 ağırlık
      - EuroLeague için hafif boost
    """
    conf = safe_float(p.get("confidence") or p.get("guven"), 0.0)
    edge = safe_float(p.get("edge"), 0.0)

    score = conf * 0.6 + edge * 0.4

    league = str(p.get("league") or "").lower()
    if "euroleague" in league or league == "el":
        score *= 1.03

    return score


def filter_and_rank_predictions(
    predictions: List[Prediction],
    preset: ModePreset,
) -> List[Prediction]:
    """
    Ortak FAZ-6 filtreleme:
      - confidence >= preset.min_confidence
      - edge >= preset.min_edge
      - skor DESC
      - max_picks sınırlaması
      - recommended_stake hesaplama
    """
    filtered: List[Prediction] = []

    for p in predictions:
        conf = safe_float(p.get("confidence") or p.get("guven"), 0.0)
        edge = safe_float(p.get("edge"), 0.0)

        if conf < preset.min_confidence:
            continue
        if edge < preset.min_edge:
            continue

        # stake hesaplama (basit ama kararlı)
        stake = preset.base_stake * max(0.5, min(2.0, (conf - 0.5) * 8.0 + edge * 20.0))
        p = dict(p)
        p["confidence"] = round(conf, 2)
        p["edge"] = round(edge, 3)
        p["recommended_stake"] = round(stake, 3)

        filtered.append(p)

    filtered.sort(key=score_prediction, reverse=True)

    if preset.max_picks is not None and len(filtered) > preset.max_picks:
        filtered = filtered[: preset.max_picks]

    return filtered
