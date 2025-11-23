import os
import json
import time
import logging
from typing import Dict, Any

import pandas as pd

# Burada iki senaryo var:
# 1) FAZ-7.9 fonksiyonları hala main.py içindeyse:
#    from main import faz79_brain, load_memory, FAZ7_DIR
# 2) Ayrı modüle taşırsan:
#    from faz7_engine.faz79_core import faz79_brain, load_memory, FAZ7_DIR

from main import faz79_brain, load_memory, FAZ7_DIR  # ilk aşamada böyle kullan

log = logging.getLogger(__name__)

FAZ10_LOG_FILE = os.path.join(FAZ7_DIR, "faz10_history.json")


def _append_log(entry: Dict[str, Any]) -> None:
    """
    FAZ-10 loglarını tek bir JSON listesi olarak tutar.
    """
    try:
        if os.path.exists(FAZ10_LOG_FILE):
            with open(FAZ10_LOG_FILE, "r") as f:
                data = json.load(f)
            if not isinstance(data, list):
                data = []
        else:
            data = []
        data.append(entry)
        with open(FAZ10_LOG_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log.warning(f"[FAZ-10] Log yazılamadı: {e}")


def faz10_stability_check(save: bool = True) -> Dict[str, Any]:
    """
    FAZ-10 – SYSTEM STABILITY ENGINE
      - FAZ-7.9 beyninden trend / vol / noise / behavior_index okur
      - Günlük stabilite skorunu hesaplar
    """
    brain = faz79_brain()

    stability = 1.0
    alerts = []

    # Trend çok düz ve hareket yoksa hafif eksi
    if brain["trend"] == "FLAT" and abs(brain["slope"]) < 0.005:
        stability -= 0.05
        alerts.append("trend_flat")

    # Noise yüksekse
    if brain["noise_ratio"] > 0.65:
        stability -= 0.15
        alerts.append("high_noise")

    # Volatilite yüksekse
    if brain["vol"] > 0.20:
        stability -= 0.10
        alerts.append("vol_spike")

    # Behavior index çökmüşse
    if brain["behavior_index"] < 0.88:
        stability -= 0.15
        alerts.append("behavior_drop")

    # Mod çok sık değişiyorsa hafif ceza (hafızadan çıkarılabilir)
    mem = load_memory()
    mode_flags = mem.get("safe", 0) + mem.get("bal", 0) + mem.get("agg", 0)
    # Çok kaba bir metrik, ileride geliştirilebilir
    if mode_flags <= 0:
        stability -= 0.05
        alerts.append("no_mode_memory")

    stability = max(0.0, min(stability, 1.0))

    result = {
        "faz": "FAZ-10",
        "ts": int(time.time()),
        "stability": round(stability, 3),
        "alerts": alerts,
        "trend": brain["trend"],
        "slope": brain["slope"],
        "vol": brain["vol"],
        "noise": brain["noise_ratio"],
        "behavior_index": brain["behavior_index"],
        "mode": brain["mode"],
    }

    if save:
        _append_log(result)
        log.info(f"[FAZ-10] Stability check: {result}")

    return result


def faz10_status_summary() -> Dict[str, Any]:
    """
    Son X FAZ-10 kaydını özetler – Telegram komutu için kullanışlı.
    """
    if not os.path.exists(FAZ10_LOG_FILE):
        return {"count": 0, "avg_stability": 1.0, "last": None}

    try:
        with open(FAZ10_LOG_FILE, "r") as f:
            data = json.load(f)
        if not data:
            return {"count": 0, "avg_stability": 1.0, "last": None}

        df = pd.DataFrame(data)
        avg_stab = float(df["stability"].mean())
        last = data[-1]
        return {
            "count": len(data),
            "avg_stability": round(avg_stab, 3),
            "last": last,
        }
    except Exception as e:
        log.warning(f"[FAZ-10] Status okunamadı: {e}")
        return {"count": 0, "avg_stability": 1.0, "last": None}
