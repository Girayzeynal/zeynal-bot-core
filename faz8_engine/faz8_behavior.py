import math
from typing import Dict, Any, List

import numpy as np


def _safe_mean(values: List[float], default: float = 0.0) -> float:
    arr = np.array(values, dtype=float)
    if arr.size == 0:
        return default
    return float(np.nanmean(arr))


def faz8_prepare_sample(
    raw_stats: Dict[str, Any],
    history_window: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    FAZ-8 ana fonksiyon:
    - Ham input (takımların son maçları, ortalama skorlar vs) alır.
    - Normalize edilmiş feature paketi döner.

    raw_stats: API/OCR'den gelen tek maç için ham veri.
    history_window: FAZ-7.9 hafızasından çekilen son X maçlık pencere.
    """

    home_scores = raw_stats.get("home_last_scores", [])
    away_scores = raw_stats.get("away_last_scores", [])

    home_avg = _safe_mean(home_scores, default=80.0)
    away_avg = _safe_mean(away_scores, default=80.0)

    pace_hint = raw_stats.get("pace_hint")  # varsa kullan
    if pace_hint is None:
        # basit tahmin: toplam ortalama + tempo katsayısı
        pace_hint = (home_avg + away_avg) * 0.97

    # form skorları (son 5 maç üzerinden win-rate gibi)
    home_form = float(raw_stats.get("home_form", 0.5))
    away_form = float(raw_stats.get("away_form", 0.5))

    # savunma / hücum index yaklaşıkları
    home_def = float(raw_stats.get("home_def_index", 0.0))
    away_def = float(raw_stats.get("away_def_index", 0.0))
    home_off = float(raw_stats.get("home_off_index", 0.0))
    away_off = float(raw_stats.get("away_off_index", 0.0))

    if history_window:
        # Hafıza penceresinden tempo düzeltmesi
        hist_totals = history_window.get("totals", [])
        hist_pace = _safe_mean(hist_totals, default=pace_hint)
        pace_hint = 0.5 * pace_hint + 0.5 * hist_pace

    base_total = pace_hint

    features = {
        "base_total": base_total,
        "home_form": home_form,
        "away_form": away_form,
        "home_off": home_off,
        "away_off": away_off,
        "home_def": home_def,
        "away_def": away_def,
    }

    # Normalizasyon (0–1 bandı)
    for k in ["home_form", "away_form"]:
        v = features[k]
        features[k] = max(0.0, min(1.0, v))

    return features


def faz8_update_global_state(
    global_state: Dict[str, Any],
    match_key: str,
    realized_total: float,
) -> Dict[str, Any]:
    """
    Maç bittikten sonra FAZ-8 global state'i hafifçe günceller.
    Bu, ileride tempo tahminlerinde küçük kaydırmalar yapmanı sağlar.
    """

    state = dict(global_state or {})
    hist = state.setdefault("history", {})
    arr = hist.setdefault(match_key, [])

    arr.append(float(realized_total))
    # pencere boyutunu çok büyütme
    if len(arr) > 40:
        arr.pop(0)

    hist[match_key] = arr
    state["history"] = hist
    return state
