import os
import json
import time
import logging

import numpy as np
import pandas as pd

# ================================================================
# 🔧 LOGGING
# ================================================================
log = logging.getLogger(__name__)


# ================================================================
# 📂 FAZ-7.9 HAFIZA DOSYASI (FAZ-9 TREND ÇEKİRDEĞİ İÇİN GİRİŞ)
# ================================================================
FAZ7_DIR = os.getenv("FAZ7_DIR", "/data/faz7")
FAZ7_MEMORY_FILE = os.path.join(FAZ7_DIR, "faz7_memory.json")


def _load_faz7_memory() -> dict:
    """
    FAZ-7.9 hafıza dosyasını okur.
    Eğer dosya yoksa minimal INIT yapı döner.
    """
    try:
        if not os.path.exists(FAZ7_MEMORY_FILE):
            log.warning(f"[FAZ-9] FAZ-7 hafıza dosyası bulunamadı: {FAZ7_MEMORY_FILE}")
            return {
                "days": [],
                "safe": 0,
                "bal": 0,
                "agg": 0,
            }

        with open(FAZ7_MEMORY_FILE, "r") as f:
            data = json.load(f)

        # Beklenen alanlar yoksa güvenli INIT
        if "days" not in data:
            data["days"] = []
        data.setdefault("safe", 0)
        data.setdefault("bal", 0)
        data.setdefault("agg", 0)

        return data
    except Exception as e:
        log.error(f"[FAZ-9] FAZ-7 hafıza okunamadı, INIT moda geçiliyor: {e}")
        return {
            "days": [],
            "safe": 0,
            "bal": 0,
            "agg": 0,
        }


# ================================================================
# 🧮 YARDIMCI FONKSİYONLAR
# ================================================================
def _safe_slope(y: pd.Series) -> float:
    """
    Küçük veri setlerinde veya sabit serilerde polyfit'in
    SVD hatasına düşmemesi için korumalı slope hesabı.
    """
    n = len(y)
    if n <= 1:
        return 0.0

    t = np.arange(n, dtype=float)
    try:
        # Derece 1 polinom (lineer trend)
        coeffs = np.polyfit(t, y.to_numpy(dtype=float), 1)
        slope = float(coeffs[0])
    except Exception as e:
        log.warning(f"[FAZ-9] Trend slope hesaplanırken hata (SVD fallback): {e}")
        slope = 0.0
    return slope


def _window_stats(df: pd.DataFrame, window: int) -> dict:
    """
    Son 'window' gün için ortalama & slope & volatilite bilgisi.
    """
    if len(df) == 0:
        return {
            "n": 0,
            "conf_mean": 0.0,
            "edge_mean": 0.0,
            "conf_slope": 0.0,
            "conf_vol": 0.0,
        }

    sub = df.tail(window)
    n = len(sub)
    conf_mean = float(sub["conf"].mean())
    edge_mean = float(sub["edge"].mean())
    conf_slope = _safe_slope(sub["conf"])
    conf_vol = float(sub["conf"].std() if n > 1 else 0.0)

    return {
        "n": n,
        "conf_mean": conf_mean,
        "edge_mean": edge_mean,
        "conf_slope": conf_slope,
        "conf_vol": conf_vol,
    }


# ================================================================
# 🧠 FAZ-9.0 TREND & REJİM ÇEKİRDEĞİ
# ================================================================
def compute_faz9_state() -> dict:
    """
    FAZ-9 ana state fonksiyonu.

    Giriş:  FAZ-7.9 memory (7 günlük pencere)
    Çıkış:  Rejim tespiti + stabilite skoru + kısa/orta/uzun trendler

    Rejim etiketleri (engine iç kullanım):
      - INIT            : yeterli veri yok
      - BULL_STRONG     : conf yüksek, trend yukarı
      - BULL_FLAT       : conf yüksek, trend yatay
      - BEAR_PRESSURE   : conf düşük, trend aşağı
      - VOLATILE        : volatilite yüksek
      - NEUTRAL         : orta seviye, karışık sinyal
    """
    mem = _load_faz7_memory()
    days = mem.get("days", [])

    if len(days) == 0:
        return {
            "engine": "FAZ-9.0",
            "regime": "INIT",
            "mode_hint": "INIT",
            "stability": 0.0,
            "windows": {},
            "raw_n_days": 0,
            "ts_last": None,
        }

    df = pd.DataFrame(days)
    # Eksik kolonlara karşı koruma
    if "conf" not in df.columns or "edge" not in df.columns:
        return {
            "engine": "FAZ-9.0",
            "regime": "INIT",
            "mode_hint": "INIT",
            "stability": 0.0,
            "windows": {},
            "raw_n_days": int(len(df)),
            "ts_last": int(df["ts"].iloc[-1]) if "ts" in df.columns else None,
        }

    # Temel pencereler: 3 / 5 / 7 gün
    win3 = _window_stats(df, 3)
    win5 = _window_stats(df, 5)
    win7 = _window_stats(df, 7)

    # Global referans: 7 günlük ortalama & slope
    g_conf = win7["conf_mean"]
    g_edge = win7["edge_mean"]
    g_slope = win7["conf_slope"]
    g_vol = win7["conf_vol"]

    # Rejim tespiti
    # -----------------
    regime = "NEUTRAL"

    # Yeterli veri yoksa INIT
    if len(df) < 3:
        regime = "INIT"
    else:
        # Önce volatilite kontrolü
        if g_vol >= 0.04:
            regime = "VOLATILE"
        else:
            # Konfor bölgeleri
            if g_conf >= 0.68 and g_edge >= 0.040:
                if g_slope > 0.010:
                    regime = "BULL_STRONG"
                else:
                    regime = "BULL_FLAT"
            elif g_conf <= 0.55 and g_edge <= 0.030 and g_slope < -0.010:
                regime = "BEAR_PRESSURE"
            else:
                regime = "NEUTRAL"

    # Mode hint (FAZ-7 memory bayraklarından)
    if mem.get("safe", 0) == 1:
        mode_hint = "SAFE"
    elif mem.get("agg", 0) == 1:
        mode_hint = "AGG"
    elif mem.get("bal", 0) == 1:
        mode_hint = "BAL"
    else:
        mode_hint = "INIT"

    # Stabilite skoru: 0.0 - 1.0 arası
    # - volatilite arttıkça düşer
    # - slope aşırı pozitif/negatif ise hafif kırpılır
    vol_penalty = min(1.0, max(0.0, g_vol * 20.0))  # ~0.05 vol → 1.0 penalty
    slope_penalty = min(0.4, abs(g_slope) * 20.0)   # aşırı trendte hafif kırp
    stability = max(0.0, 1.0 - vol_penalty - slope_penalty)

    ts_last = None
    if "ts" in df.columns:
        try:
            ts_last = int(df["ts"].iloc[-1])
        except Exception:
            ts_last = None

    return {
        "engine": "FAZ-9.0",
        "regime": regime,
        "mode_hint": mode_hint,
        "stability": round(stability, 3),
        "windows": {
            "win3": win3,
            "win5": win5,
            "win7": win7,
        },
        "raw_n_days": int(len(df)),
        "g_conf": round(g_conf, 3),
        "g_edge": round(g_edge, 3),
        "g_slope": round(g_slope, 4),
        "g_vol": round(g_vol, 4),
        "ts_last": ts_last,
    }


# ================================================================
# 🎯 FAZ-9 BOOST FONKSİYONU
#   (FAZ-8.4 / FAZ-6 çıktılarının üstüne hafif düzeltme katmanı)
# ================================================================
def faz9_boost_signal(base_conf: float,
                      base_edge: float,
                      base_stake: float = 1.0) -> dict:
    """
    FAZ-9 boost katmanı:

    Giriş:
      - base_conf  : FAZ-8.3 / FAZ-8.4 sonrası güven skoru
      - base_edge  : FAZ-8.x sonrası edge
      - base_stake : FAZ-8.x sonrası stake

    Çıkış:
      - conf/edge/stake → FAZ-9 rejim & stabiliteye göre hafif ayarlanmış
      - state          → compute_faz9_state() çıktısının özeti
    """
    state = compute_faz9_state()
    regime = state["regime"]
    stability = state["stability"]

    conf = float(base_conf)
    edge = float(base_edge)
    stake = float(base_stake)

    # INIT veya veri yoksa → dokunma, direkt passthrough
    if regime == "INIT" or state["raw_n_days"] == 0:
        return {
            "engine": "FAZ-9.0",
            "regime": regime,
            "stability": stability,
            "conf": round(conf, 3),
            "edge": round(edge, 3),
            "stake": round(stake, 2),
            "state": state,
        }

    # --- Rejim bazlı ana çarpanlar ---
    conf_mult = 1.0
    edge_mult = 1.0
    stake_mult = 1.0

    if regime == "BULL_STRONG":
        conf_mult *= 1.02
        edge_mult *= 1.03
        stake_mult *= 1.06
    elif regime == "BULL_FLAT":
        conf_mult *= 1.01
        edge_mult *= 1.02
        stake_mult *= 1.03
    elif regime == "BEAR_PRESSURE":
        conf_mult *= 0.96
        edge_mult *= 0.94
        stake_mult *= 0.88
    elif regime == "VOLATILE":
        conf_mult *= 0.97
        edge_mult *= 0.97
        stake_mult *= 0.80
    elif regime == "NEUTRAL":
        # çok hafif smoothing
        conf_mult *= 1.00
        edge_mult *= 1.00
        stake_mult *= 0.98

    # Stabilite etkisi:
    #  stability ~1.0  → +%5 stake buff
    #  stability ~0.0  → -%5 stake nerf
    stake_mult *= (0.95 + 0.10 * stability)

    # Mode hint'e göre ufak düzeltme
    mode_hint = state["mode_hint"]
    if mode_hint == "SAFE":
        stake_mult *= 0.92
        conf_mult *= 1.01
    elif mode_hint == "AGG":
        stake_mult *= 1.05
        conf_mult *= 0.99
    # BAL / INIT → nötr

    # Uygula
    conf = conf * conf_mult
    edge = edge * edge_mult
    stake = stake * stake_mult

    # Güvenlik clamp'leri
    conf = max(0.0, min(0.99, conf))
    edge = max(0.0, edge)
    stake = max(0.1, stake)

    return {
        "engine": "FAZ-9.0",
        "regime": regime,
        "stability": round(stability, 3),
        "conf": round(conf, 3),
        "edge": round(edge, 3),
        "stake": round(stake, 2),
        "state": state,
    }


# ================================================================
# 🧪 LOKAL TEST (isteğe bağlı)
#   fly.io üzerinde module olarak import edildiğinde çalışmaz.
#   Sadece manuel Python çalıştırırken hızlı test için.
# ================================================================
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    log.info("[FAZ-9] Lokal test başlıyor...")
    s = compute_faz9_state()
    log.info(f"[FAZ-9] State: {json.dumps(s, indent=2)}")

    demo = faz9_boost_signal(0.63, 0.038, 1.0)
    log.info(f"[FAZ-9] Demo boost: {json.dumps(demo, indent=2)}")
