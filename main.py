import os
import time
import json
import logging
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor

import telebot
import numpy as np
import pandas as pd
from flask import Flask, request


# ================================================================
#   🔍 GLOBAL OCR DEBUG + CACHE
# ================================================================

LAST_OCR_TEXT = None
LAST_OCR_META = {}

OCR_CACHE = {}
OCR_CACHE_LOCK = threading.Lock()

# Worker havuzu — FAZ-13.4 PRO daha agresif OCR işlemine izin verir
OCR_EXECUTOR = ThreadPoolExecutor(
    max_workers=int(os.getenv("OCR_MAX_WORKERS", "6"))
)

TESSERACT_TIMEOUT = float(os.getenv("OCR_TESSERACT_TIMEOUT", "1.8"))
EASYOCR_TIMEOUT = float(os.getenv("OCR_EASYOCR_TIMEOUT", "2.8"))
VISION_TIMEOUT = float(os.getenv("OCR_VISION_TIMEOUT", "6.0"))

GPU_MODE = os.getenv("GPU_MODE", "AUTO").upper()   # AUTO / FORCE / OFF
VISION_MODE = os.getenv("VISION_MODE", "ON").upper() == "ON"


# ================================================================
#   🔌 FAZ-10 / 11 / 12 / 13 IMPORTLARI (Pipeline Modülleri)
# ================================================================

from faz10_engine.faz10_stability import faz10_stability_check
from faz11_engine.faz11_feedback import faz11_feedback, faz11_last_summary
from faz12_engine.faz12_autoadjust import faz12_run_once, faz12_auto_profile
from faz13_engine.faz13_orchestrator import (
    normalize_manual_text,
    normalize_visual_meta,
    normalize_api_data,
    run_faz13_auto_pipeline,
    faz13_daily_coupon,
    faz13_upcoming_coupon,
    faz13_league_coupon,
    faz13_live_coupon,
)


# ================================================================
#   🧩 OCR BACKEND IMPORTS (Soft imports)
# ================================================================

try:
    from PIL import Image
    import pytesseract
except Exception:
    Image = None
    pytesseract = None

try:
    import easyocr
except Exception:
    easyocr = None

try:
    import openai
except Exception:
    openai = None


# ================================================================
#   🔧 GLOBAL PATHS
# ================================================================

FAZ7_DIR = os.getenv("FAZ7_DIR", "/data/faz7")
MEMORY_FILE = os.path.join(FAZ7_DIR, "faz7_memory.json")
FAZ11_LOG_FILE = os.path.join(FAZ7_DIR, "faz11_history.json")


# ================================================================
#   🛠 ENGINEERING MODE (FAZ-10 HardSync master switch)
# ================================================================

ENGINEERING_MODE = os.getenv("ENGINEERING_MODE", "ON").upper() == "ON"


# ================================================================
#   📝 LOGGING
# ================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


# ================================================================
#   🤖 TELEGRAM BOT
# ================================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env değişkeni tanımlı değil!")

bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode="HTML",
    disable_web_page_preview=True,
)


# ================================================================
#   🌐 FLASK ROUTES (webhook + health)
# ================================================================

app = Flask(__name__)

@app.route("/", methods=["GET"])
def home():
    return "OK", 200


@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    try:
        json_update = request.get_json(silent=True)
        if json_update is None:
            raw_body = request.data.decode("utf-8", errors="ignore")
            log.warning(f"Webhook JSON parse hatası, raw: {raw_body[:500]}")
            return "OK", 200

        update = telebot.types.Update.de_json(json_update)
        bot.process_new_updates([update])

    except Exception as e:
        log.error(f"Webhook hata: {e}", exc_info=True)

    return "OK", 200
    
# ================================================================
# 📌 FAZ-7.9 v2.0 MEMORY ENGINE  (Kalıcı volume destekli)
# ================================================================
def init_memory():
    try:
        os.makedirs(FAZ7_DIR, exist_ok=True)
    except Exception as e:
        log.error(f"[FAZ-7.9] Hafıza klasörü oluşturulamadı: {e}")

    if not os.path.exists(MEMORY_FILE):
        data = {
            "days": [],
            "safe": 0,
            "bal": 0,
            "agg": 0,
        }
        try:
            with open(MEMORY_FILE, "w") as f:
                json.dump(data, f, indent=4)
            log.info(f"[FAZ-7.9] Yeni memory dosyası oluşturuldu: {MEMORY_FILE}")
        except Exception as e:
            log.error(f"[FAZ-7.9] Memory dosyası oluşturulamadı: {e}")


def load_memory():
    init_memory()
    try:
        with open(MEMORY_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        log.error(f"[FAZ-7.9] Memory yüklenemedi, resetleniyor: {e}")
        data = {
            "days": [],
            "safe": 0,
            "bal": 0,
            "agg": 0,
        }
        with open(MEMORY_FILE, "w") as f:
            json.dump(data, f, indent=4)
        return data


def save_memory(data):
    try:
        with open(MEMORY_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        log.error(f"[FAZ-7.9] Memory kaydedilemedi: {e}")


def register_daily_stats(conf: float, edge: float):
    mem = load_memory()
    today = {
        "ts": int(time.time()),
        "conf": float(conf),
        "edge": float(edge),
    }

    mem["days"].append(today)

    if len(mem["days"]) > 7:
        mem["days"] = mem["days"][-7:]

    save_memory(mem)
    log.info(f"[FAZ-7.9] Günlük kayıt eklendi: conf={conf:.3f}, edge={edge:.3f}")


def _ema(series: pd.Series, alpha: float = 0.6) -> float:
    if len(series) == 0:
        return 0.0
    ema_val = series.iloc[0]
    for x in series.iloc[1:]:
        ema_val = alpha * x + (1 - alpha) * ema_val
    return float(ema_val)


def _faz92_behavior_curves(df: pd.DataFrame, slope: float, vol: float) -> dict:
    if df is None or len(df) == 0:
        return {
            "tci": 0.0,
            "noise_ratio": 0.0,
            "stability": 1.0,
            "momentum": 0.0,
            "behavior_index": 1.0,
        }

    conf_series = df["conf"].astype(float)
    edge_series = df["edge"].astype(float)

    last_conf = float(conf_series.iloc[-1])
    first_conf = float(conf_series.iloc[0])
    conf_change = last_conf - first_conf

    conf_std = float(conf_series.std() if len(conf_series) > 1 else 0.0)
    edge_std = float(edge_series.std() if len(edge_series) > 1 else 0.0)

    stability = 1.0 / (1.0 + conf_std * 25.0)
    stability = max(0.0, min(stability, 1.0))

    momentum = max(-0.1, min(conf_change, 0.1))

    denom = conf_std + 0.02
    tci = abs(slope) / denom
    tci = max(0.0, min(tci, 1.0))

    noise_ratio = vol / (abs(conf_change) + 0.01)
    noise_ratio = max(0.0, min(noise_ratio, 1.5))

    behavior_index = 1.0
    behavior_index += momentum * 0.8 * 10.0
    if noise_ratio > 0.6:
        behavior_index -= (noise_ratio - 0.6) * 0.2
    behavior_index -= vol * 0.5
    behavior_index = max(0.8, min(behavior_index, 1.2))

    return {
        "tci": round(tci, 3),
        "noise_ratio": round(noise_ratio, 3),
        "stability": round(stability, 3),
        "momentum": round(momentum, 3),
        "behavior_index": round(behavior_index, 3),
    }


def faz79_brain():
    """
    FAZ-7.9 v2.0 STRATEJİ BEYNİ + FAZ-9.1/9.2
    """
    mem = load_memory()
    days = mem["days"]

    if len(days) == 0:
        return {
            "mode": "INIT",
            "conf": 0.0,
            "edge": 0.0,
            "trend": "INIT",
            "slope": 0.0,
            "vol": 0.0,
            "tci": 0.0,
            "noise_ratio": 0.0,
            "behavior_index": 1.0,
            "stability": 1.0,
            "momentum": 0.0,
            "stake_norm": 1.00,
            "safe": False,
            "bal": True,
            "agg": False,
        }

    df = pd.DataFrame(days)
    df["t"] = range(len(df))

    avg_conf = float(df["conf"].mean())
    avg_edge = float(df["edge"].mean())

    try:
        slope = float(np.polyfit(df["t"], df["conf"], 1)[0])
    except Exception as e:
        log.warning(f"FAZ-7.9 v2.0 slope hesaplanırken hata (SVD fallback): {e}")
        slope = 0.0

    ema_conf = _ema(df["conf"])
    if slope > 0.01 and ema_conf >= avg_conf:
        trend = "UP"
    elif slope < -0.01 and ema_conf <= avg_conf:
        trend = "DOWN"
    else:
        trend = "FLAT"

    base_vol = float(df["conf"].std() if len(df) > 1 else 0.0)
    ema_diff = abs(ema_conf - avg_conf)
    vol = float(base_vol * 0.8 + ema_diff * 0.2)

    bc = _faz92_behavior_curves(df, slope, vol)
    tci = bc["tci"]
    noise_ratio = bc["noise_ratio"]
    behavior_index = bc["behavior_index"]
    stability = bc["stability"]
    momentum = bc["momentum"]

    if avg_conf >= 0.72 and avg_edge >= 0.045:
        mode = "SAFE"
    elif avg_conf >= 0.58 and avg_edge >= 0.030:
        mode = "BAL"
    else:
        mode = "AGG"

    mem["safe"] = int(mode == "SAFE")
    mem["bal"] = int(mode == "BAL")
    mem["agg"] = int(mode == "AGG")
    save_memory(mem)

    return {
        "mode": mode,
        "conf": round(avg_conf, 3),
        "edge": round(avg_edge, 3),
        "trend": trend,
        "slope": round(slope, 4),
        "vol": round(vol, 4),
        "tci": tci,
        "noise_ratio": noise_ratio,
        "behavior_index": behavior_index,
        "stability": stability,
        "momentum": momentum,
        "stake_norm": 1.00,
        "safe": mode == "SAFE",
        "bal": mode == "BAL",
        "agg": mode == "AGG",
    }


# ================================================================
# 🧠 FAZ-8 FULL ENGINE (8.1 + 8.2 + 8.3 + 8.4 + 8.5 unified)
# ================================================================
def faz8_calibrate_signal(
    raw_conf: float,
    raw_edge: float,
    base_stake: float = 1.0
) -> dict:
    """
    FAZ-8.x unified calibration engine.
    FAZ-7.9 beynine göre güven / edge / stake düzeltmesi uygulanır.
    """
    brain = faz79_brain()   # FAZ-7.9 + FAZ-9.x birleşik beyin

    conf = float(raw_conf)
    edge = float(raw_edge)
    stake = float(base_stake)

    mode = brain["mode"]
    trend = brain["trend"]
    vol = float(brain["vol"])
    conf_avg = max(brain["conf"], 0.01)
    edge_avg = max(brain["edge"], 0.005)

    if mode == "SAFE":
        conf += 0.02
        edge *= 1.05
        stake *= 0.88
    elif mode == "BAL":
        pass
    elif mode == "AGG":
        conf -= 0.02
        edge *= 0.95
        stake *= 1.18

    if trend == "UP":
        conf += 0.01
        edge *= 1.03
    elif trend == "DOWN":
        conf -= 0.01
        edge *= 0.97

    if vol > 0.18:
        conf -= 0.02
        stake *= 0.85
    elif vol < 0.05:
        conf += 0.01
        stake *= 1.05

    conf = max(0.0, min(0.99, conf))
    edge = max(0.0, edge)
    stake = max(0.10, stake)

    score = 0.6 * (conf / conf_avg) + 0.4 * (edge / edge_avg)

    if score < 0.95:
        bucket = "LOW"
    elif score < 1.10:
        bucket = "MID"
    else:
        bucket = "HIGH"

    return {
        "engine": "FAZ-8",
        "mode": mode,
        "trend": trend,
        "vol": round(vol, 4),
        "conf": round(conf, 3),
        "edge": round(edge, 3),
        "stake": round(stake, 2),
        "bucket": bucket,
        "score": round(score, 3),
        "behavior_index": brain["behavior_index"],
    }


# ================================================================
# 🧠 FAZ-8.4 COUPON ENGINE (SAFE / BAL / AGG / ULTRA)
# ================================================================
def faz84_coupon_engine(
    profile: str,
    conf: float,
    edge: float,
    base_stake: float = 1.0
):
    mode = profile.upper()
    stake = float(base_stake)

    if mode == "SAFE":
        stake *= 0.90
    elif mode == "BAL":
        stake *= 1.00
    elif mode == "AGG":
        stake *= 1.15
    elif mode == "ULTRA":
        stake *= 1.30

    stake = max(0.10, stake)

    return {
        "mode": mode,
        "conf": conf,
        "edge": edge,
        "stake": round(stake, 2),
        "risk": mode,
        "bucket": "MID",
    }


# ================================================================
# 🧠 FAZ-8.5 META PROFILE SELECTOR
# ================================================================
def faz85_meta_profile_selector() -> str:
    brain = faz79_brain()
    mode = brain["mode"]

    if mode == "SAFE":
        return "SAFE"
    elif mode == "BAL":
        return "BAL"
    elif mode == "AGG":
        return "AGG"
    return "BAL"


# ================================================================
# 🔁 FAZ-10 → HardSync Mode
# ================================================================
def faz10_hardsync(brain: dict, calib: dict | None = None) -> dict:
    try:
        stability = faz10_stability_check(brain) or {}
    except Exception as e:
        log.error(f"[FAZ-10] Stability check hata: {e}", exc_info=True)
        stability = {}

    regime = str(stability.get("regime", "NORMAL") or "NORMAL").upper()
    suggested_mode = str(
        stability.get("suggested_mode", brain.get("mode", "INIT"))
        or brain.get("mode", "INIT")
    ).upper()

    try:
        score = float(stability.get("stability_score", 1.0) or 1.0)
    except Exception:
        score = 1.0

    try:
        anomaly = float(stability.get("anomaly_level", 0.0) or 0.0)
    except Exception:
        anomaly = 0.0

    base_mode = str(brain.get("mode", "INIT") or "INIT").upper()
    bucket = (calib or {}).get("bucket", "MID")

    final_mode = base_mode
    lock_reason = "NO_LOCK"

    if ENGINEERING_MODE:
        if regime in ("CRITICAL", "UNSTABLE") or anomaly >= 0.7 or score < 0.60:
            final_mode = "SAFE"
            lock_reason = "CRITICAL_LOCK"
        elif score < 0.75 or anomaly >= 0.4:
            if base_mode == "AGG":
                final_mode = "BAL"
                lock_reason = "AGG_DOWNGRADE"
            else:
                final_mode = base_mode
                lock_reason = "SOFT_GUARD"
        else:
            if suggested_mode in ("SAFE", "BAL", "AGG"):
                final_mode = suggested_mode
                lock_reason = "FOLLOW_SUGGESTED"
            else:
                final_mode = base_mode
                lock_reason = "BASE_MODE"
    else:
        final_mode = base_mode
        lock_reason = "ENGINEERING_OFF"

    info = {
        "brain": brain,
        "stability": stability,
        "mode": final_mode,
        "bucket": bucket,
        "lock_reason": lock_reason,
        "stability_score": score,
        "anomaly_level": anomaly,
        "regime": regime,
        "engineering_mode": ENGINEERING_MODE,
    }

    log.info(
        "[FAZ-10][HardSync] mode=%s → %s | bucket=%s | score=%.3f | anomaly=%.3f | regime=%s | reason=%s",
        base_mode,
        final_mode,
        bucket,
        score,
        anomaly,
        regime,
        lock_reason,
    )

    return info


# ================================================================
# 🧩 FAZ-11 & FAZ-12 WRAPPERS
# ================================================================
def _faz11_register_feedback(real_results, predicted, save=True):
    try:
        return faz11_feedback(real_results, predicted, save=save)
    except Exception as e:
        log.error(f"[FAZ-11] Feedback çalıştırılamadı: {e}", exc_info=True)
        return {"error": str(e)}


def _faz12_autoadjust(f10_state, f11_state):
    try:
        decision = faz12_run_once(f10_state, f11_state)
        log.info(f"[FAZ-12] Auto adjust tamamlandı: {decision}")
        return decision
    except Exception as e:
        log.error(f"[FAZ-12] Auto adjust çalıştırılamadı: {e}", exc_info=True)
        return {"error": str(e)}


def _auto_faz_pipeline(
    pred_conf: float = 0.60,
    pred_edge: float = 0.03,
    pred_bucket: str = "MID",
    real_result: bool | None = None,
):
    """
    Otomatik FAZ-10 → FAZ-11 → FAZ-12 pipeline
    """
    try:
        brain = faz79_brain()
        f10 = faz10_stability_check(brain)

        if real_result is not None:
            real = [bool(real_result)]
            predicted = [{
                "conf": float(pred_conf),
                "edge": float(pred_edge),
                "bucket": str(pred_bucket),
            }]
            _faz11_register_feedback(real, predicted, save=True)

        f11_summary = faz11_last_summary()
        f11_last = f11_summary.get("last", {})

        if f11_last:
            _faz12_autoadjust(f10, f11_last)

    except Exception as e:
        log.error(f"[AutoPipeline] Hata: {e}", exc_info=True)


# ================================================================
# 🏀 FAZ-6 v3 – KUPON & NBA SİMÜLASYON
# ================================================================
def _faz84_from_raw(
    profile: str,
    raw_conf: float,
    raw_edge: float,
    base_stake: float
) -> dict:
    return faz84_coupon_engine(profile, raw_conf, raw_edge, base_stake)


def _build_fixture_legs():
    legs = []

    # Kupon 1 — SAFE (10 maç)
    k1_games = [
        ("EL:EFES@REAL | REAL MADRID -5.5 (FT spread)", 0.66, 0.045, 0.88),
        ("EL:FENER@OLY | OLYMPIACOS -3.5 (FT spread)", 0.64, 0.041, 0.84),
        ("NBA:BOS@MIA | UNDER 112.5 (1. Yarı total)", 0.65, 0.040, 0.80),
        ("NBA:LAL@DEN | DEN +1.5 (Q1 spread)", 0.64, 0.039, 0.78),
        ("NBA:GSW@PHX | UNDER 58.5 (Q2 total)", 0.63, 0.038, 0.76),
        ("NBA:MIA@MIL | MIA +4.5 (FT spread)", 0.66, 0.044, 0.86),
        ("EL:PARTIZAN@EFES | EFES -2.5 (FT spread)", 0.64, 0.040, 0.82),
        ("EL:BARCA@FENER | UNDER 82.5 (1. Yarı total)", 0.65, 0.039, 0.80),
        ("NBA:NYK@CHI | UNDER 55.5 (Q1 total)", 0.64, 0.038, 0.78),
        ("NBA:DAL@SAC | DAL +2.5 (FT spread)", 0.66, 0.043, 0.88),
    ]
    for g in k1_games:
        legs.append((1, *g))

    # Kupon 2 — BALANCED (10 maç)
    k2_games = [
        ("NBA:BOS@MIA | UNDER 224.5 (FT total)", 0.63, 0.036, 0.80),
        ("NBA:LAL@DEN | DEN -4.5 (FT spread)", 0.61, 0.032, 0.76),
        ("EL:PARTIZAN@EFES | OVER 79.5 (1. Yarı total)", 0.62, 0.034, 0.78),
        ("NBA:NYK@CHI | NYK -1.5 (Q3 spread)", 0.60, 0.031, 0.74),
        ("NBA:DAL@SAC | OVER 56.5 (Q4 total)", 0.60, 0.030, 0.74),
        ("NBA:PHX@GSW | PHX +3.5 (FT spread)", 0.62, 0.035, 0.78),
        ("NBA:MEM@LAC | UNDER 111.5 (2. Yarı total)", 0.61, 0.033, 0.76),
        ("EL:OLY@BARCA | BARCA ML (FT moneyline)", 0.62, 0.034, 0.79),
        ("EL:VALENCIA@FENER | FENER -2.5 (Q3 spread)", 0.60, 0.031, 0.74),
        ("NBA:ATL@MIA | UNDER 57.5 (Q2 total)", 0.61, 0.032, 0.75),
    ]
    for g in k2_games:
        legs.append((2, *g))

    # Kupon 3 — AGGRESSIVE (10 maç)
    k3_games = [
        ("NBA:CHI@NYK | NYK ML (FT moneyline)", 0.60, 0.031, 0.75),
        ("NBA:MIA@MIL | MIA +2.5 (Q1 spread)", 0.59, 0.030, 0.74),
        ("NBA:PHI@BOS | OVER 113.5 (2. Yarı total)", 0.59, 0.029, 0.72),
        ("EL:FENER@REAL | FENERBAHÇE +4.5 (FT spread)", 0.58, 0.029, 0.72),
        ("NBA:LAC@GSW | LAC ML (Q4 moneyline)", 0.58, 0.028, 0.70),
        ("NBA:SAC@DEN | OVER 118.5 (2. Yarı total)", 0.59, 0.029, 0.72),
        ("NBA:OKC@DAL | OKC +3.5 (FT spread)", 0.58, 0.028, 0.70),
        ("EL:EFES@OLY | OVER 82.5 (2. Yarı total)", 0.58, 0.028, 0.70),
        ("EL:PARTIZAN@REAL | PARTIZAN +7.5 (FT spread)", 0.57, 0.027, 0.69),
        ("NBA:BKN@NYK | OVER 56.5 (Q4 total)", 0.57, 0.027, 0.68),
    ]
    for g in k3_games:
        legs.append((3, *g))

    # Kupon 4 — ULTRA (10 maç)
    k4_games = [
        ("NBA:GSW@PHX | OVER 230.5 (FT total)", 0.59, 0.028, 0.73),
        ("NBA:DAL@LAL | DAL -3.5 (FT spread)", 0.58, 0.027, 0.72),
        ("NBA:NYK@BKN | NYK -1.5 (HT spread)", 0.58, 0.027, 0.70),
        ("EL:EFES@BAYERN | OVER 41.5 (Q1 total)", 0.57, 0.026, 0.68),
        ("EL:FENER@OLY | OVER 79.5 (2. Yarı total)", 0.57, 0.026, 0.68),
        ("NBA:MIA@BOS | OVER 60.5 (Q3 total)", 0.58, 0.027, 0.71),
        ("NBA:CHI@ATL | ATL -2.5 (FT spread)", 0.57, 0.026, 0.69),
        ("EL:REAL@BARCA | OVER 165.5 (FT total)", 0.57, 0.026, 0.69),
        ("EL:OLY@PARTIZAN | OLY -3.5 (FT spread)", 0.56, 0.025, 0.67),
        ("NBA:UTA@PHX | PHX -4.5 (FT spread)", 0.56, 0.025, 0.67),
    ]
    for g in k4_games:
        legs.append((4, *g))

    return legs


def build_faz6_coupons_text() -> str:
    legs = _build_fixture_legs()

    def fmt(game: str, calib: dict) -> str:
        return (
            f"{game}\n"
            f"  Güven: {calib['conf']:.2f} | "
            f"Edge: {calib['edge']:.3f} | "
            f"Stake: {calib['stake']:.2f} | "
            f"Risk: {calib['risk']} | Mode: {calib['mode']}\n"
        )

    parts = []
    parts.append(
        "🔥 <b>FAZ-6 v3 KUPONLARI</b> "
        "(40 maç / FAZ-8.4 Kupon Motoru + FAZ-8.5 META hafıza uyumlu)\n\n"
    )

    for coupon_id in (1, 2, 3, 4):
        if coupon_id == 1:
            title = "🔥Kupon 1 — SAFE [SAFE]"
            profile = "SAFE"
        elif coupon_id == 2:
            title = "🔥Kupon 2 — BALANCED [BAL]"
            profile = "BAL"
        elif coupon_id == 3:
            title = "🔥Kupon 3 — AGGRESSIVE [AGG]"
            profile = "AGG"
        else:
            title = "🔥Kupon 4 — ULTRA [ULTRA]"
            profile = "ULTRA"

        parts.append(title + "\n")
        total_stake = 0.0

        for leg in [l for l in legs if l[0] == coupon_id]:
            _, game_desc, conf, edge, stake = leg
            calib = _faz84_from_raw(profile, conf, edge, stake)
            parts.append(fmt(game_desc, calib))
            total_stake += calib["stake"]

        parts.append(f"💰 Toplam Stake: {total_stake:.2f}\n")
        parts.append("— — —\n\n")

    return "".join(parts)


def build_faz6_meta_coupon_text() -> str:
    profile = faz85_meta_profile_selector()

    legs_def = [
        ("NBA:MIA@NYK | MIA -2.5 (FT spread)", 0.64, 0.039, 0.85),
        ("EL:FENER@EFES | OVER 164.5 (FT total)", 0.62, 0.034, 0.80),
        ("NBA:MIA@NYK | OVER 52.5 (Q1 total)", 0.63, 0.036, 0.78),
        ("NBA:MIA@NYK | NYK +1.5 (Q3 spread)", 0.61, 0.032, 0.76),
    ]

    def fmt(game: str, calib: dict) -> str:
        return (
            f"{game}\n"
            f"  Güven: {calib['conf']:.2f} | "
            f"Edge: {calib['edge']:.3f} | "
            f"Stake: {calib['stake']:.2f} | "
            f"Risk: {calib['risk']} | Mode: {calib['mode']}\n"
        )

    legs_text = []
    total_stake = 0.0
    for game, conf, edge, stake in legs_def:
        calib = _faz84_from_raw(profile, conf, edge, stake)
        legs_text.append(fmt(game, calib))
        total_stake += calib["stake"]

    text = (
        "🤖 <b>FAZ-6 META KUPON (FAZ-8.5 Profile Selector v3)</b>\n\n"
        f"Seçilen Profil: <b>{profile}</b>\n\n"
        + "".join(legs_text)
        + f"💰 Toplam Stake: {total_stake:.2f}\n"
    )
    return text


def _send_long_text(message, text: str, max_len: int = 3800):
    chat_id = message.chat.id
    if len(text) <= max_len:
        bot.reply_to(message, text)
        return

    start = 0
    first = True
    while start < len(text):
        chunk = text[start:start + max_len]
        if first:
            bot.reply_to(message, chunk)
            first = False
        else:
            bot.send_message(chat_id, chunk)
        start += max_len


def build_nba_simulation_text():
    """
    NBA simülasyon çıktı örneği
    """
    home = "MIA"
    away = "NYK"
    skor = 104
    tempo = 98.8
    pace = 98.8

    raw_conf = 0.62
    raw_edge = 0.034

    profile = faz85_meta_profile_selector()
    c = faz84_coupon_engine(profile, raw_conf, raw_edge, base_stake=1.0)

    _auto_faz_pipeline(
        pred_conf=c.get("conf", 0.60),
        pred_edge=c.get("edge", 0.03),
        pred_bucket=c.get("bucket", "MID"),
        real_result=None,
    )

    win_team = home
    win_prob = c["conf"]

    risk_label = {
        "SAFE": "🛡 SAFE",
        "BAL": "⚖ BALANCED",
        "AGG": "⚡ AGGRESSIVE",
        "INIT": "⏳ INIT",
    }.get(c["mode"], c["mode"])

    return (
        "🏀 <b>NBA Simülasyon Sonuçları (FAZ-8.4 + FAZ-8.5 META)</b>\n\n"
        f"🏠 {home} vs ✈️ {away}\n"
        f"📈 Tahmini Skor: <b>{skor}</b>\n"
        f"⏱ Tempo: <b>{tempo}</b>\n"
        f"🎯 Kazanan: <b>{win_team}</b> ({int(win_prob * 100)}%)\n"
        f"📊 Risk Profili: {risk_label} | Bucket: <b>{c['bucket']}</b>\n"
        f"🔍 Edge: <b>{c['edge']:.3f}</b>\n"
        f"💰 Stake: <b>{c['stake']:.2f}</b>\n\n"
        f"🔧 Profil (FAZ-8.5): <b>{profile}</b>\n\n"
        "🧠 <b>Ham Analiz</b>:\n"
        "🔥 <b>NBA – Canlı Maçlar</b>\n"
        f"🏀 {home} (54) – {away} (50)\n"
        f"⏱ Pace Tahmini: <b>{pace}</b>"
    )

# ================================================================
#   📸 OCR ENGINE v13.4 PRO — CORE
#   (Tesseract + EasyOCR + OpenAI Vision Hybrid)
# ================================================================

def ocr_cache_key(image_bytes: bytes) -> str:
    return hashlib.sha256(image_bytes).hexdigest()


def ocr_cache_get(key: str):
    with OCR_CACHE_LOCK:
        return OCR_CACHE.get(key)


def ocr_cache_set(key: str, value: dict):
    with OCR_CACHE_LOCK:
        OCR_CACHE[key] = value
        if len(OCR_CACHE) > 100:
            OCR_CACHE.pop(next(iter(OCR_CACHE)))


# ---------------------------
#  Tesseract Worker
# ---------------------------
def _tesseract_worker(image_bytes: bytes) -> dict:
    if pytesseract is None:
        return {"text": "", "confidence": 0.0, "engine": "tesseract", "error": "not installed"}

    try:
        import io
        img = Image.open(io.BytesIO(image_bytes))
        text = pytesseract.image_to_string(img)
        return {
            "text": text.strip(),
            "confidence": 0.45,
            "engine": "tesseract",
        }
    except Exception as e:
        return {"text": "", "confidence": 0.0, "engine": "tesseract", "error": str(e)}


# ---------------------------
#  EasyOCR Worker
# ---------------------------
def _easyocr_worker(image_bytes: bytes) -> dict:
    if easyocr is None:
        return {"text": "", "confidence": 0.0, "engine": "easyocr", "error": "not installed"}

    try:
        import io
        reader = easyocr.Reader(["en"], gpu=(GPU_MODE != "OFF"))
        img = Image.open(io.BytesIO(image_bytes))
        results = reader.readtext(np.array(img))

        lines = []
        conf_sum = 0.0
        for (bbox, txt, conf) in results:
            lines.append(txt)
            conf_sum += float(conf)

        text = "\n".join(lines)
        avg_conf = conf_sum / max(len(results), 1)

        return {
            "text": text.strip(),
            "confidence": float(avg_conf),
            "engine": "easyocr",
        }
    except Exception as e:
        return {"text": "", "confidence": 0.0, "engine": "easyocr", "error": str(e)}


# ---------------------------
#  OpenAI Vision Worker (v13.4 PRO)
# ---------------------------
def _vision_worker(image_bytes: bytes) -> dict:
    if not VISION_MODE or openai is None:
        return {"text": "", "confidence": 0.0, "engine": "vision", "error": "vision off"}

    try:
        import base64
        b64_img = base64.b64encode(image_bytes).decode("utf-8")

        prompt = (
            "Extract ALL structured text exactly as visible. "
            "Do NOT summarize. Preserve formatting. "
            "Return plain text only."
        )

        res = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": f"data:image/jpeg;base64,{b64_img}"}
                    ],
                },
            ],
            max_tokens=1200,
        )

        text = res.choices[0].message["content"].strip()
        return {
            "text": text,
            "confidence": 0.92,
            "engine": "vision",
        }
    except Exception as e:
        return {"text": "", "confidence": 0.0, "engine": "vision", "error": str(e)}


# ================================================================
#   🤖 OCR ENGINE v13.4 — HYBRID RUNNER
# ================================================================
def run_ocr_v134(image_bytes: bytes) -> dict:
    key = ocr_cache_key(image_bytes)
    cached = ocr_cache_get(key)
    if cached:
        return cached

    future_tess = OCR_EXECUTOR.submit(_tesseract_worker, image_bytes)
    future_easy = OCR_EXECUTOR.submit(_easyocr_worker, image_bytes)

    results = []
    try:
        results.append(future_tess.result(timeout=TESSERACT_TIMEOUT))
    except Exception:
        pass

    try:
        results.append(future_easy.result(timeout=EASYOCR_TIMEOUT))
    except Exception:
        pass

    if VISION_MODE:
        try:
            results.append(_vision_worker(image_bytes))
        except Exception:
            pass

    results.sort(key=lambda x: x.get("confidence", 0.0), reverse=True)
    best = results[0] if results else {"text": "", "confidence": 0.0, "engine": "none"}

    ocr_cache_set(key, best)

    global LAST_OCR_TEXT, LAST_OCR_META
    LAST_OCR_TEXT = best.get("text", "")
    LAST_OCR_META = best

    return best


# ================================================================
#   🧠 FAZ-13.4 PRO CLASSIFIER
# ================================================================
def faz134_classifier(text: str) -> str:
    t = text.lower()

    if any(k in t for k in ["oran", "bet", "iddaa", "1.25", "2.05", "handicap"]):
        return "odds"
    if any(k in t for k in ["fg", "reb", "ast", "to", "pace", "def", "off"]):
        return "stats"
    if any(k in t for k in ["h2h", "son 5", "karşılaşma geçmişi"]):
        return "history"
    if any(k in t for k in ["q1", "q2", "q3", "q4", "first half", "2nd half"]):
        return "period"
    if any(k in t for k in ["injury", "out", "doubtful", "rotasyon"]):
        return "injury"
    if any(k in t for k in ["live", "canlı", "quarter", "timeout"]):
        return "live"
    if any(k in t for k in ["efes", "fener", "barça", "real madrid", "bayern"]):
        return "teams"

    return "generic"


# ================================================================
#   🧪 MULTI-SCREEN FUSION (FAZ-13.4 PRO)
# ================================================================
def faz134_fusion(screens: list) -> dict:
    merged = {
        "text": "",
        "sources": [],
        "classes": [],
        "has_odds": False,
        "has_stats": False,
        "has_history": False,
        "visual_strength": 0.0,
    }

    for sc in screens:
        txt = sc.get("text", "")
        cls = sc.get("cls", "generic")
        conf = sc.get("confidence", 0.0)

        merged["text"] += "\n" + txt
        merged["sources"].append(sc)
        merged["classes"].append(cls)

        if cls == "odds":
            merged["has_odds"] = True
        if cls == "stats":
            merged["has_stats"] = True
        if cls == "history":
            merged["has_history"] = True

        merged["visual_strength"] += conf / 3.0

    merged["visual_strength"] = round(min(1.0, merged["visual_strength"]), 3)
    return merged


# ================================================================
#   📡 COMMAND: /start
# ================================================================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    bot.reply_to(
        message,
        "🏀 <b>Hoş geldin!</b>\n"
        "Bu bot FAZ-13.4 PRO Basketbol Motoru ile çalışıyor.\n"
        "Görsel gönder → otomatik tahmin.\n"
        "/mac → manuel tahmin.\n"
        "/mac_img → çoklu görsel ile PRO tahmin."
    )


# ================================================================
#   📡 COMMAND: /status — FAZ durumu
# ================================================================
@bot.message_handler(commands=["status"])
def cmd_status(message):
    brain = faz79_brain()
    text = (
        "<b>FAZ-13.4 PRO Sistem Durumu</b>\n\n"
        f"🎯 Mode: {brain['mode']}\n"
        f"📈 Trend: {brain['trend']}\n"
        f"📊 Stability: {brain['stability']:.3f}\n"
        f"🔧 Engineering Mode: {ENGINEERING_MODE}\n"
    )
    bot.reply_to(message, text)


# ================================================================
#   📡 COMMAND: /faz6
# ================================================================
@bot.message_handler(commands=["faz6"])
def cmd_faz6(message):
    text = build_faz6_coupons_text()
    _send_long_text(message, text)


@bot.message_handler(commands=["faz6_meta"])
def cmd_faz6_meta(message):
    text = build_faz6_meta_coupon_text()
    _send_long_text(message, text)


# ================================================================
#   📡 COMMAND: /mac (MANUAL INPUT → FAZ-13)
# ================================================================
@bot.message_handler(commands=["mac"])
def cmd_mac(message):
    try:
        raw = message.text.replace("/mac", "").strip()
        if not raw:
            bot.reply_to(message, "🔎 Maç metnini yaz örnek:\n/mac Fenerbahçe vs Efes +7.5 over 164.5")
            return

        manual = normalize_manual_text(raw)
        result = run_faz13_auto_pipeline(manual_text=manual)

        bot.reply_to(
            message,
            f"🏀 <b>FAZ-13 Tahmin</b>\n\n"
            f"{result}"
        )
    except Exception as e:
        bot.reply_to(message, f"❗ Hata: {e}")


# ================================================================
#   📸 COMMAND: /mac_img (FAZ-13.4 PRO MULTI-SCREEN)
# ================================================================
@bot.message_handler(commands=["mac_img"])
def cmd_mac_img(message):
    bot.reply_to(message, "📸 Görselleri gönder — 1 maç için 1-20 adet desteklenir.")


@bot.message_handler(content_types=["photo"])
def cmd_mac_img_reader(message):
    try:
        file_id = message.photo[-1].file_id
        file = bot.get_file(file_id)
        image_bytes = bot.download_file(file.file_path)

        ocr = run_ocr_v134(image_bytes)
        cls = faz134_classifier(ocr["text"])

        fuse = message.chat.id
        if not hasattr(bot, "img_sessions"):
            bot.img_sessions = {}

        if fuse not in bot.img_sessions:
            bot.img_sessions[fuse] = []

        bot.img_sessions[fuse].append({
            "text": ocr["text"],
            "cls": cls,
            "confidence": ocr["confidence"],
        })

        bot.reply_to(
            message,
            f"📸 Görsel alındı (cls={cls}, conf={ocr['confidence']:.2f})\n"
            f"Toplam ekran: {len(bot.img_sessions[fuse])}"
        )

        if len(bot.img_sessions[fuse]) >= 3:
            screens = bot.img_sessions[fuse]
            fusion = faz134_fusion(screens)
            manual = normalize_visual_meta(fusion)

            result = run_faz13_auto_pipeline(
                manual_text=manual,
                visual_meta=fusion
            )

            bot.send_message(
                message.chat.id,
                f"🏀 <b>FAZ-13.4 PRO Tahmin (Multi-Screen)</b>\n\n{result}"
            )

            bot.img_sessions[fuse] = []

    except Exception as e:
        bot.reply_to(message, f"❗ Görsel hata: {e}")


# ================================================================
#   🧪 COMMAND: /ocr_debug
# ================================================================
@bot.message_handler(commands=["ocr_debug"])
def cmd_ocr_dbg(message):
    bot.reply_to(
        message,
        f"<b>Son OCR</b>\n\n"
        f"{LAST_OCR_TEXT}\n\n"
        f"<b>Meta</b>:\n{json.dumps(LAST_OCR_META, indent=2)}"
    )


# ================================================================
#   🌐 WEBHOOK SETUP
# ================================================================
def setup_webhook():
    if not WEBHOOK_URL:
        raise RuntimeError("WEBHOOK_URL tanımlı değil!")
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=WEBHOOK_URL)
    log.info(f"Webhook bağlandı: {WEBHOOK_URL}")


# ================================================================
#   🚀 BOOTSTRAP
# ================================================================
if __name__ == "__main__":
    setup_webhook()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
