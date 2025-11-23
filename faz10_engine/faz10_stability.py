import os
import json
import logging
from typing import Optional, Dict, Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# FAZ-7.9 hafızasının tutulduğu klasör
FAZ7_DIR = os.getenv("FAZ7_DIR", "/data/faz7")
MEMORY_FILE = os.path.join(FAZ7_DIR, "faz7_memory.json")


def _load_faz7_memory() -> Dict[str, Any]:
    """
    FAZ-7.9 hafıza dosyasını direkt okur.
    main.py'den import ETMEZ, circular import riskini engellemek için
    dosyaya kendisi erişir.
    """
    try:
        os.makedirs(FAZ7_DIR, exist_ok=True)
    except Exception as e:
        log.error(f"[FAZ-10] Hafıza klasörü oluşturulamadı: {e}")

    if not os.path.exists(MEMORY_FILE):
        # hiç veri yoksa boş şema döndür
        return {"days": [], "safe": 0, "bal": 0, "agg": 0}

    try:
        with open(MEMORY_FILE, "r") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            data = {}

        data.setdefault("days", [])
        data.setdefault("safe", 0)
        data.setdefault("bal", 0)
        data.setdefault("agg", 0)

        return data
    except Exception as e:
        log.error(f"[FAZ-10] Memory okunamadı, boş döndürülüyor: {e}")
        return {"days": [], "safe": 0, "bal": 0, "agg": 0}


def _compute_trend(series: pd.Series) -> float:
    """
    Basit lineer trend (slope). Hata durumunda 0.0 döner.
    """
    if series is None or len(series) < 2:
        return 0.0

    try:
        x = np.arange(len(series))
        slope = float(np.polyfit(x, series.values.astype(float), 1)[0])
        return slope
    except Exception as e:
        log.warning(f"[FAZ-10] Trend hesaplanamadı: {e}")
        return 0.0


def _normalize(value: float, low: float, high: float) -> float:
    """
    value'yi [low, high] aralığında 0-1'e sıkıştır.
    Ters scale gerekiyorsa low/high parametresiyle oynanır.
    """
    if high <= low:
        return 0.0
    v = (value - low) / (high - low)
    return max(0.0, min(1.0, v))


def faz10_stability_check(
    brain_snapshot: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    FAZ-10 STABILITY ENGINE (v1.0)

    - FAZ-7.9 hafıza dosyasını okur.
    - conf/edge zaman serilerinden:
        * std, range, slope, son gün farkları
    - Opsiyonel olarak main.py'den gelen brain_snapshot (faz79_brain output)
      ile vol / tci / behavior_index'i hesaba katar.
    - 0-100 arası stability_score üretir.
    - 4 rejim tanımlar:
        ULTRA_STABLE / STABLE / UNSTABLE / CHAOTIC
    - Aynı zamanda hafif bir "önerilen strateji modu" verir.
    """

    # --- hafızayı sadece FONKSİYON İÇİNDE yüklüyoruz (import sırasında değil) ---
    mem = _load_faz7_memory()
    days = mem.get("days", [])

    if not days:
        # Hiç veri yoksa INIT dön
        return {
            "engine": "FAZ-10",
            "status": "INIT",
            "stability_score": 50.0,
            "regime": "INIT",
            "conf_std": 0.0,
            "edge_std": 0.0,
            "conf_range": 0.0,
            "edge_range": 0.0,
            "trend_slope": 0.0,
            "last_conf": None,
            "last_edge": None,
            "recent_jump": 0.0,
            "anomaly_level": 0.0,
            "brain_vol": 0.0,
            "brain_tci": 0.0,
            "behavior_index": 1.0,
            "suggested_mode": "BAL",
        }

    # pandas DataFrame'e çevir
    df = pd.DataFrame(days)

    # Güvenlik: numeric cast
    df["conf"] = df["conf"].astype(float)
    df["edge"] = df["edge"].astype(float)

    conf_series = df["conf"]
    edge_series = df["edge"]

    conf_std = float(conf_series.std()) if len(conf_series) > 1 else 0.0
    edge_std = float(edge_series.std()) if len(edge_series) > 1 else 0.0

    conf_range = float(conf_series.max() - conf_series.min())
    edge_range = float(edge_series.max() - edge_series.min())

    trend_slope = _compute_trend(conf_series)

    if len(conf_series) >= 2:
        recent_jump = float(conf_series.iloc[-1] - conf_series.iloc[-2])
    else:
        recent_jump = 0.0

    # --- FAZ-10 ana skor: volatility + jump + trend kombinasyonu ---

    # Volatility normalizasyonu: conf_std ~ [0.0, 0.10] arası beklenir
    vol_norm = _normalize(conf_std, 0.0, 0.10)

    # Range normalizasyonu: conf_range ~ [0.0, 0.30] arası beklenir
    range_norm = _normalize(conf_range, 0.0, 0.30)

    # Jump normalizasyonu: |recent_jump| ~ [0.0, 0.20]
    jump_norm = _normalize(abs(recent_jump), 0.0, 0.20)

    # Trend büyüklüğü: |slope| ~ [0.0, 0.03]
    trend_norm = _normalize(abs(trend_slope), 0.0, 0.03)

    # Brain snapshot'tan opsiyonel olarak vol / tci / behavior_index al
    brain_vol = 0.0
    brain_tci = 0.0
    behavior_index = 1.0

    if brain_snapshot:
        try:
            brain_vol = float(brain_snapshot.get("vol", 0.0))
        except Exception:
            brain_vol = 0.0

        try:
            brain_tci = float(brain_snapshot.get("tci", 0.0))
        except Exception:
            brain_tci = 0.0

        try:
            behavior_index = float(brain_snapshot.get("behavior_index", 1.0))
        except Exception:
            behavior_index = 1.0

    brain_vol_norm = _normalize(brain_vol, 0.0, 0.20)
    brain_tci_norm = _normalize(brain_tci, 0.0, 1.0)
    behavior_deviation = abs(behavior_index - 1.0)
    behavior_norm = _normalize(behavior_deviation, 0.0, 0.30)

    # Anomali skoru: yüksek vol + yüksek jump + yüksek behavior sapması
    anomaly_level = (
        0.35 * vol_norm
        + 0.25 * jump_norm
        + 0.20 * behavior_norm
        + 0.20 * trend_norm
    )
    anomaly_level = max(0.0, min(anomaly_level, 1.0))

    # Stabilite skoru: düşük anomali + yüksek tci -> yüksek stabilite
    stability_raw = (
        0.55 * (1.0 - anomaly_level)
        + 0.25 * (1.0 - brain_vol_norm)
        + 0.20 * brain_tci_norm
    )
    stability_raw = max(0.0, min(stability_raw, 1.0))
    stability_score = round(stability_raw * 100.0, 1)

    # Rejimler:
    if stability_score >= 82:
        regime = "ULTRA_STABLE"
    elif stability_score >= 65:
        regime = "STABLE"
    elif stability_score >= 48:
        regime = "UNSTABLE"
    else:
        regime = "CHAOTIC"

    # Önerilen strateji modu:
    # Not: Bu sadece “öneri”; gerçek mod değişimi main.py'de yapılabilir.
    if regime == "ULTRA_STABLE":
        suggested_mode = "AGG"
    elif regime == "STABLE":
        suggested_mode = "BAL"
    elif regime == "UNSTABLE":
        suggested_mode = "SAFE"
    else:  # CHAOTIC
        suggested_mode = "SAFE"

    last_conf = float(conf_series.iloc[-1])
    last_edge = float(edge_series.iloc[-1])

    return {
        "engine": "FAZ-10",
        "status": "OK",
        "stability_score": stability_score,
        "regime": regime,
        "conf_std": round(conf_std, 4),
        "edge_std": round(edge_std, 4),
        "conf_range": round(conf_range, 4),
        "edge_range": round(edge_range, 4),
        "trend_slope": round(trend_slope, 5),
        "last_conf": round(last_conf, 4),
        "last_edge": round(last_edge, 4),
        "recent_jump": round(recent_jump, 4),
        "anomaly_level": round(anomaly_level, 4),
        "brain_vol": round(brain_vol, 4),
        "brain_tci": round(brain_tci, 4),
        "behavior_index": round(behavior_index, 4),
        "suggested_mode": suggested_mode,
    }
