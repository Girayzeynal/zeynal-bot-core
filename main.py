import os
import json
import time
import logging

import telebot
import numpy as np
import pandas as pd
from flask import Flask, request

# ================================================================
# 🔗 FAZ-10 / FAZ-11 / FAZ-12 / FAZ-13 IMPORTLARI
# ================================================================
from faz10_engine.faz10_stability import faz10_stability_check

from faz11_engine.faz11_feedback import (
    faz11_feedback,
    faz11_last_summary
)

from faz12_engine.faz12_autoadjust import (
    faz12_run_once,
    faz12_auto_profile
)

from faz13_engine.faz13_orchestrator import (
    normalize_manual_text,
    normalize_api_data,
    normalize_visual_meta,
    run_faz13_auto_pipeline,
    faz13_daily_coupon,
    faz13_upcoming_coupon,
    faz13_league_coupon,
    faz13_live_coupon,
    faz13_visual_coupon_from_text,
) 


# ================================================================
# 🔧 GLOBAL PATHLER
# ================================================================
FAZ7_DIR = os.getenv("FAZ7_DIR", "/data/faz7")
MEMORY_FILE = os.path.join(FAZ7_DIR, "faz7_memory.json")
FAZ11_LOG_FILE = os.path.join(FAZ7_DIR, "faz11_history.json")


# ================================================================
# 🔧 ENGINEERING MODE (FAZ-10 HardSync için global switch)
# ================================================================
ENGINEERING_MODE = os.getenv("ENGINEERING_MODE", "ON").upper() == "ON"

# ================================================================
# 🔧 LOGGING
# ================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ================================================================
# 🔧 CONFIG
# ================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Örn: https://zeynal-bot-core.fly.dev/webhook

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env değişkeni tanımlı değil!")

if not WEBHOOK_URL:
    log.warning("WEBHOOK_URL tanımlı değil! Webhook set edilemeyecek.")

# Telegram bot
bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode="HTML",
    disable_web_page_preview=True,
)

# ================================================================
# 🌐 FLASK APP (Health check + Webhook)
# ================================================================
app = Flask(__name__)


@app.route("/", methods=["GET"])
def home():
    return "OK", 200


@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    try:
        json_update = request.get_json(force=False, silent=True)
        if json_update is None:
            raw_body = request.data.decode("utf-8", errors="ignore")
            log.warning(f"Webhook JSON parse edilemedi, raw body: {raw_body[:500]}")
            return "OK", 200

        update = telebot.types.Update.de_json(json_update)
        bot.process_new_updates([update])
    except Exception as e:
        log.error(f"Webhook update işlenirken hata: {e}", exc_info=True)
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
#   Minimal but 100% functional & stable for Fly.io
# ================================================================

def faz8_calibrate_signal(raw_conf: float,
                          raw_edge: float,
                          base_stake: float = 1.0) -> dict:
    """
    FAZ-8.x unified calibration engine.
    FAZ-7.9 beynine göre güven / edge / stake düzeltmesi uygulanır.
    8.1 + 8.2 + 8.3 davranışı minimal stabil formda entegre edildi.
    """

    brain = faz79_brain()   # FAZ-7.9 + FAZ-9.x birleşik beyin

    # ------------------------------------------------------------
    # 1) RAW INPUT
    # ------------------------------------------------------------
    conf = float(raw_conf)
    edge = float(raw_edge)
    stake = float(base_stake)

    mode = brain["mode"]
    trend = brain["trend"]
    vol = float(brain["vol"])
    conf_avg = max(brain["conf"], 0.01)
    edge_avg = max(brain["edge"], 0.005)

    # ------------------------------------------------------------
    # 2) MODE EFFECTS (FAZ-8.1)
    # ------------------------------------------------------------
    if mode == "SAFE":
        conf += 0.02
        edge *= 1.05
        stake *= 0.88
    elif mode == "BAL":
        conf += 0.00
        edge *= 1.00
        stake *= 1.00
    elif mode == "AGG":
        conf -= 0.02
        edge *= 0.95
        stake *= 1.18

    # ------------------------------------------------------------
    # 3) TREND EFFECTS (UP / DOWN)
    # ------------------------------------------------------------
    if trend == "UP":
        conf += 0.01
        edge *= 1.03
    elif trend == "DOWN":
        conf -= 0.01
        edge *= 0.97

    # ------------------------------------------------------------
    # 4) VOLATILITY EFFECTS (FAZ-8.2 LMF SHIELD)
    # ------------------------------------------------------------
    if vol > 0.18:
        conf -= 0.02
        stake *= 0.85
    elif vol < 0.05:
        conf += 0.01
        stake *= 1.05

    # ------------------------------------------------------------
    # 5) LIMITS
    # ------------------------------------------------------------
    conf = max(0.0, min(0.99, conf))
    edge = max(0.0, edge)
    stake = max(0.10, stake)

    # ------------------------------------------------------------
    # 6) BUCKET SCORE (FAZ-8.3 dynamic)
    # ------------------------------------------------------------
    score = 0.6 * (conf / conf_avg) + 0.4 * (edge / edge_avg)

    if score < 0.95:
        bucket = "LOW"
    elif score < 1.10:
        bucket = "MID"
    else:
        bucket = "HIGH"

    # ------------------------------------------------------------
    # 7) RETURN STRUCTURE
    # ------------------------------------------------------------
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
def faz84_coupon_engine(profile: str,
                        conf: float,
                        edge: float,
                        base_stake: float = 1.0):
    """
    FAZ-8.4: Kupon bacağı kalibrasyonu (minimal working version).
    """
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
# 🧠 FAZ-8.5 META PROFILE SELECTOR (FAZ-7.9 beynine göre)
# ================================================================
def faz85_meta_profile_selector() -> str:
    """
    FAZ-85 META PROFIL SEÇİCİ
    FAZ-7.9 beyin moduna göre SAFE/BAL/AGG seçer.
    """
    brain = faz79_brain()
    mode = brain["mode"]

    if mode == "SAFE":
        return "SAFE"
    elif mode == "BAL":
        return "BAL"
    elif mode == "AGG":
        return "AGG"

    return "BAL"   # fallback


# ================================================================
# 🔁 FAZ-10 → HardSync Mode (FAZ-7.9 + FAZ-8 + FAZ-9.x + FAZ-10)
# ================================================================
def faz10_hardsync(brain: dict, calib: dict = None) -> dict:
    """
    FAZ-10 HardSync
    """
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
# 🧠 FAZ-8.1 / 8.2 / 8.3
# ================================================================
def _faz81_core_calibration(raw_conf: float,
                            raw_edge: float,
                            base_stake: float = 1.0) -> dict:
    brain = faz79_brain()

    mode = brain["mode"]
    trend = brain["trend"]
    vol = brain["vol"]

    conf = float(raw_conf)
    edge = float(raw_edge)
    stake = float(base_stake)

    if mode not in ("SAFE", "BAL", "AGG"):
        return {
            "engine": "FAZ-8.1",
            "mode": mode,
            "trend": trend,
            "vol": round(vol, 4),
            "conf": round(conf, 3),
            "edge": round(edge, 3),
            "stake": round(stake, 2),
        }

    if mode == "SAFE":
        stake_factor = 0.88
        conf_boost = 0.035
    elif mode == "BAL":
        stake_factor = 1.00
        conf_boost = 0.00
    else:  # AGG
        stake_factor = 1.18
        conf_boost = -0.025

    if trend == "UP":
        conf += 0.02
        edge *= 1.06
    elif trend == "DOWN":
        conf -= 0.02
        edge *= 0.94

    if vol > 0.18:
        conf -= 0.02
        stake_factor *= 0.90
    elif vol < 0.05 and mode == "SAFE":
        conf += 0.01
        edge *= 1.03

    conf += conf_boost

    conf = max(0.0, min(conf, 0.99))
    edge = max(0.0, edge)
    stake = max(0.1, stake * stake_factor)

    return {
        "engine": "FAZ-8.1",
        "mode": mode,
        "trend": trend,
        "vol": round(vol, 4),
        "conf": round(conf, 3),
        "edge": round(edge, 3),
        "stake": round(stake, 2),
    }


def _faz82_lmf_shield(calib: dict) -> dict:
    mode = calib.get("mode", "INIT")
    trend = calib.get("trend", "INIT")
    vol = float(calib.get("vol", 0.0))
    conf = float(calib.get("conf", 0.0))
    edge = float(calib.get("edge", 0.0))
    stake = float(calib.get("stake", 1.0))

    profiles = {
        "SAFE": {
            "edge_floor": 0.030,
            "edge_hard_floor": 0.020,
            "vol_soft": 0.08,
            "vol_hard": 0.18,
            "trend_up_factor": 1.05,
            "trend_down_factor": 0.88,
        },
        "BAL": {
            "edge_floor": 0.028,
            "edge_hard_floor": 0.018,
            "vol_soft": 0.10,
            "vol_hard": 0.22,
            "trend_up_factor": 1.04,
            "trend_down_factor": 0.90,
        },
        "AGG": {
            "edge_floor": 0.025,
            "edge_hard_floor": 0.015,
            "vol_soft": 0.12,
            "vol_hard": 0.26,
            "trend_up_factor": 1.03,
            "trend_down_factor": 0.92,
        },
    }

    prof = profiles.get(mode, profiles["BAL"])

    if edge < prof["edge_hard_floor"]:
        stake *= 0.45
        conf *= 0.80
    elif edge < prof["edge_floor"]:
        stake *= 0.70
        conf *= 0.90

    if vol > prof["vol_hard"]:
        stake *= 0.65
        conf *= 0.90
    elif vol > prof["vol_soft"]:
        stake *= 0.80
        conf *= 0.95

    if trend == "DOWN":
        stake *= prof["trend_down_factor"]
        conf *= prof["trend_down_factor"]
    elif trend == "UP":
        stake *= prof["trend_up_factor"]
        conf *= prof["trend_up_factor"]

    conf = max(0.0, min(conf, 0.99))
    edge = max(0.0, edge)
    stake = max(0.1, stake)

    calib["engine"] = "FAZ-8.2"
    calib["conf"] = round(conf, 3)
    calib["edge"] = round(edge, 3)
    calib["stake"] = round(stake, 2)
    return calib


def faz83_compute_risk_bucket(conf: float,
                              edge: float,
                              conf_avg: float,
                              edge_avg: float):
    conf_avg = max(conf_avg, 1e-6)
    edge_avg = max(edge_avg, 1e-6)

    rel_conf = conf / conf_avg
    rel_edge = edge / edge_avg

    score = 0.6 * rel_conf + 0.4 * rel_edge

    if score < 0.95:
        bucket = "LOW"
    elif score < 1.10:
        bucket = "MID"
    else:
        bucket = "HIGH"

    return bucket, round(score, 4)


def faz83_dynamic_calibration(conf: float,
                              edge: float,
                              stake: float,
                              mode: str,
                              trend_slope: float,
                              vol: float,
                              conf_avg: float,
                              edge_avg: float) -> dict:
    bucket, score = faz83_compute_risk_bucket(conf, edge, conf_avg, edge_avg)

    base_mult_map = {"LOW": 0.70, "MID": 0.90, "HIGH": 1.10}
    base_mult = base_mult_map[bucket]

    slope_clamped = max(min(trend_slope, 0.05), -0.05)
    trend_mult = 1.0 + (slope_clamped * 1.5)

    vol_clamped = max(min(vol, 0.08), 0.0)
    vol_mult = 1.0 - (vol_clamped * 1.5)

    mode = (mode or "BAL").upper()
    if mode == "SAFE":
        mode_mult = 0.85
    elif mode == "AGG":
        mode_mult = 1.10
    else:
        mode_mult = 1.0

    total_mult = base_mult * trend_mult * vol_mult * mode_mult
    total_mult = max(0.40, min(total_mult, 1.40))

    cal_stake = round(stake * total_mult, 2)

    if bucket == "LOW":
        conf_mult = 0.92
        edge_mult = 0.92
    elif bucket == "MID":
        conf_mult = 0.97
        edge_mult = 0.97
    else:
        conf_mult = 1.02
        edge_mult = 1.00

    cal_conf = max(0.0, min(0.99, conf * conf_mult))
    cal_edge = max(0.0, edge * edge_mult)

    return {
        "engine": "FAZ-8.3",
        "bucket": bucket,
        "score": score,
        "raw_conf": round(conf, 3),
        "raw_edge": round(edge, 3),
        "raw_stake": round(stake, 2),
        "cal_conf": round(cal_conf, 3),
        "cal_edge": round(cal_edge, 3),
        "cal_stake": cal_stake,
    }


# ================================================================
# 🧩 FAZ-11 & FAZ-12 GLOBAL WRAPPERS + AUTO PIPELINE
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


def _auto_faz_pipeline(pred_conf: float = 0.60,
                       pred_edge: float = 0.03,
                       pred_bucket: str = "MID",
                       real_result: bool | None = None):
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
                "bucket": str(pred_bucket)
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
def _faz84_from_raw(profile: str,
                    raw_conf: float,
                    raw_edge: float,
                    base_stake: float) -> dict:
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
        f"Seçilen Profil: <b>{profile}</b>\n\n" +
        "".join(legs_text) +
        f"💰 Toplam Stake: {total_stake:.2f}\n"
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
    NBA simülasyon çıktı örneği:
      RAW → FAZ-8.4 (kupon motoru referanslı)
      Profil FAZ-8.5 META selector ile seçilir.
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

    # AUTO PIPELINE: FAZ-10 → FAZ-11 → FAZ-12
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
# 🧠 FAZ-7.9 & FAZ-8 KOMUTLARI
# ================================================================
@bot.message_handler(commands=["faz7_status"])
def faz7_status(message):
    mem = load_memory()

    if len(mem["days"]) == 0:
        msg = "📊 <b>FAZ-7.9 Hafıza:</b> Henüz veri yok."
    else:
        df = pd.DataFrame(mem["days"])
        msg = (
            "📊 <b>FAZ-7.9 v2.0 HAFIZA ÖZETİ</b>\n\n"
            f"SAFE: {mem['safe']}\n"
            f"BAL : {mem['bal']}\n"
            f"AGG : {mem['agg']}\n\n"
            f"7 Günlük Ortalama Confidence: <b>{df['conf'].mean():.3f}</b>\n"
            f"7 Günlük Ortalama Edge: <b>{df['edge'].mean():.3f}</b>"
        )

    bot.reply_to(message, msg)


@bot.message_handler(commands=["faz7_plan"])
def faz7_plan(message):
    info = faz79_brain()

    msg = (
        "🧠 <b>FAZ-7.9 v2.0 STRATEJİ BEYNİ + FAZ-9.1 + FAZ-9.2</b>\n\n"
        f"Mod: <b>{info['mode']}</b>\n"
        f"Günlük: conf={info['conf']} edge={info['edge']}\n"
        f"Trend: {info['trend']} (slope {info['slope']})\n"
        f"Volatilite: {info['vol']}\n"
        f"Trend Certainty (TCI): {info['tci']}\n"
        f"Noise Ratio: {info['noise_ratio']}\n"
        f"Behavior Index: {info['behavior_index']}\n"
        f"Stake Normalize: {info['stake_norm']}\n\n"
        f"SAFE: {'✅' if info['safe'] else '❌'}\n"
        f"BAL: {'✅' if info['bal'] else '❌'}\n"
        f"AGG: {'✅' if info['agg'] else '❌'}\n"
    )

    bot.reply_to(message, msg)


@bot.message_handler(commands=["faz7_register"])
def faz7_register_cmd(message):
    try:
        parts = message.text.split()
        if len(parts) != 3:
            bot.reply_to(
                message,
                "✅ Kullanım: <code>/faz7_register conf edge</code>\n"
                "Örn: <code>/faz7_register 0.62 0.035</code>",
            )
            return

        conf = float(parts[1])
        edge = float(parts[2])

        register_daily_stats(conf, edge)
        info = faz79_brain()

        bot.reply_to(
            message,
            (
                "✅ Günlük FAZ-7.9 v2.0 kaydı alındı.\n\n"
                f"conf={conf:.3f}, edge={edge:.3f}\n"
                f"Yeni Mod: <b>{info['mode']}</b>\n"
                f"Trend: {info['trend']} (slope {info['slope']})"
            ),
        )
    except Exception as e:
        bot.reply_to(message, f"❌ Kayıt hatası: {e}")


@bot.message_handler(commands=["faz8_status"])
def faz8_status(message):
    raw_conf = 0.64
    raw_edge = 0.038
    base_stake = 1.0

    calib = faz8_calibrate_signal(raw_conf, raw_edge, base_stake)

    msg = (
        "🧪 <b>FAZ-8.x STATUS</b>\n\n"
        f"Mode: <b>{calib['mode']}</b>\n"
        f"Trend: {calib['trend']} | Vol: {calib['vol']}\n"
        f"Engine: <b>{calib.get('engine','FAZ-8.3')}</b>\n"
        f"Bucket: <b>{calib['bucket']}</b> | Score: {calib['score']}\n"
        f"Behavior Index: <b>{calib.get('behavior_index', 1.0):.3f}</b>\n\n"
        f"Cal → conf=<b>{calib['conf']:.3f}</b>, "
        f"edge=<b>{calib['edge']:.3f}</b>, "
        f"stake=<b>{calib['stake']:.2f}</b>\n"
    )
    bot.reply_to(message, msg)


@bot.message_handler(commands=["faz8_test"])
def faz8_test(message):
    try:
        parts = message.text.split()
        if len(parts) not in (3, 4):
            bot.reply_to(
                message,
                "✅ Kullanım: <code>/faz8_test conf edge [stake]</code>\n"
                "Örn: <code>/faz8_test 0.63 0.035 0.80</code>",
            )
            return

        raw_conf = float(parts[1])
        raw_edge = float(parts[2])
        base_stake = float(parts[3]) if len(parts) == 4 else 1.0

        calib = faz8_calibrate_signal(raw_conf, raw_edge, base_stake)

        msg = (
            "🧪 <b>FAZ-8.3 FULL TEST</b>\n\n"
            f"Input: conf={raw_conf:.3f}, edge={raw_edge:.3f}, stake={base_stake:.2f}\n\n"
            f"Mode: <b>{calib['mode']}</b> | Trend: {calib['trend']} | Vol: {calib['vol']}\n"
            f"Bucket: <b>{calib['bucket']}</b> | Score: {calib['score']}\n"
            f"Behavior Index: <b>{calib.get('behavior_index', 1.0):.3f}</b>\n\n"
            f"Output → conf=<b>{calib['conf']:.3f}</b>, "
            f"edge=<b>{calib['edge']:.3f}</b>, "
            f"stake=<b>{calib['stake']:.2f}</b>\n"
        )
        bot.reply_to(message, msg)
    except Exception as e:
        bot.reply_to(message, f"❌ FAZ-8 test hatası: {e}")


@bot.message_handler(commands=["faz83_test"])
def faz83_test(message):
    try:
        parts = message.text.split()
        if len(parts) not in (3, 4):
            bot.reply_to(
                message,
                "✅ Kullanım: <code>/faz83_test conf edge [stake]</code>\n"
                "Örn: <code>/faz83_test 0.63 0.035 0.80</code>",
            )
            return

        raw_conf = float(parts[1])
        raw_edge = float(parts[2])
        base_stake = float(parts[3]) if len(parts) == 4 else 1.0

        c = faz8_calibrate_signal(raw_conf, raw_edge, base_stake)
        brain = faz79_brain()

        msg = (
            "🧪 <b>FAZ-8.3 FULL PIPELINE</b>\n\n"
            f"Input RAW → conf={raw_conf:.3f}, edge={raw_edge:.3f}, stake={base_stake:.2f}\n\n"
            f"FAZ-7.9 v2.0 Brain + FAZ-9.x → mode=<b>{brain['mode']}</b>, "
            f"trend={brain['trend']} (slope {brain['slope']}), vol={brain['vol']}\n"
            f"TCI={brain['tci']}, Noise={brain['noise_ratio']}, "
            f"BehaviorIndex={brain['behavior_index']}\n"
            f"7g avg → conf={brain['conf']}, edge={brain['edge']}\n\n"
            f"FAZ-8.3 → bucket=<b>{c['bucket']}</b>, score={c['score']}\n"
            f"Calibrated → conf=<b>{c['conf']:.3f}</b>, "
            f"edge=<b>{c['edge']:.3f}</b>, "
            f"stake=<b>{c['stake']:.2f}</b>\n"
        )
        bot.reply_to(message, msg)
    except Exception as e:
        bot.reply_to(message, f"❌ FAZ-8.3 test hatası: {e}")


# ================================================================
# FAZ-6 KOMUTLARI
# ================================================================
@bot.message_handler(commands=["faz6_coupon", "kupon"])
def faz6_coupon(message):
    try:
        text = build_faz6_coupons_text()
        _send_long_text(message, text)
    except Exception as e:
        log.error(f"FAZ-6 kupon oluşturma hatası: {e}", exc_info=True)
        bot.reply_to(message, "❌ Kupon üretiminde hata oluştu.")


@bot.message_handler(commands=["faz6_meta", "kupon_meta"])
def faz6_meta(message):
    try:
        text = build_faz6_meta_coupon_text()
        bot.reply_to(message, text)
    except Exception as e:
        log.error(f"FAZ-6 META kupon hatası: {e}", exc_info=True)
        bot.reply_to(message, "❌ META kupon üretiminde hata oluştu.")


@bot.message_handler(commands=["simulate_nba"])
def cmd_simulate_nba(message):
    try:
        bot.reply_to(
            message,
            "🏀 Simülasyon başlatılıyor (FAZ-8.4 + FAZ-8.5 META + FAZ-9.x)...",
        )
        text = build_nba_simulation_text()
        bot.reply_to(message, text)
    except Exception as e:
        log.error(f"Simülasyon hatası: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Simülasyon hatası: {e}")


# Basit FAZ-6 placeholder komutları
@bot.message_handler(commands=["faz6_test"])
def faz6_test(message):
    bot.reply_to(message, "🧪 FAZ-6 Test modu placeholder.")


@bot.message_handler(commands=["faz6_auto"])
def faz6_auto(message):
    bot.reply_to(message, "🤖 FAZ-6 Auto modu placeholder.")


@bot.message_handler(commands=["faz6_risk"])
def faz6_risk(message):
    bot.reply_to(message, "⚠️ FAZ-6 Risk modu placeholder.")


@bot.message_handler(commands=["faz6_edge"])
def faz6_edge(message):
    bot.reply_to(message, "📐 FAZ-6 Edge modu placeholder.")


@bot.message_handler(commands=["faz6_real"])
def faz6_real(message):
    bot.reply_to(message, "📊 FAZ-6 Real modu placeholder.")


@bot.message_handler(commands=["faz6_balance"])
def faz6_balance(message):
    bot.reply_to(message, "⚖ FAZ-6 Balance modu placeholder.")


# ================================================================
# 🧰 GENEL KOMUTLAR (/start, /help, /status, /faz10, /faz11, /faz12)
# ================================================================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    text = (
        "🔥 <b>Bot aktif!</b>\n"
        "FAZ-4 + FAZ-5 + FAZ-6 v3 + FAZ-7.9 v2.0 + "
        "FAZ-8.2 + FAZ-8.3 + FAZ-8.4 + FAZ-8.5 META + FAZ-9.x + FAZ-10 HardSync + "
        "FAZ-11 + FAZ-12 + FAZ-13 bağlı.\n"
        "Komut listesi için <code>/help</code> yaz."
    )
    bot.reply_to(message, text)


@bot.message_handler(commands=["help"])
def cmd_help(message):
    text = (
        "📌 <b>Komutlar</b>:\n\n"
        "/start - Botu başlatır\n"
        "/help - Komut listesi\n"
        "/status - Sistem durumu\n\n"
        "/simulate_nba - NBA canlı simülasyon (FAZ-8.4 + FAZ-8.5 + FAZ-9.x)\n\n"
        "— <b>FAZ-6 v3</b> —\n"
        "/faz6_test - FAZ-6 Test\n"
        "/faz6_auto - FAZ-6 Auto\n"
        "/faz6_risk - FAZ-6 Risk\n"
        "/faz6_edge - FAZ-6 Edge\n"
        "/faz6_real - FAZ-6 Real\n"
        "/faz6_balance - FAZ-6 Balance\n"
        "/faz6_coupon - FAZ-6 v3 Kupon (40 maç / FAZ-8.4 kupon motoru)\n"
        "/faz6_meta - FAZ-6 META kupon (FAZ-8.5 profile selector)\n\n"
        "— <b>FAZ-7.9</b> —\n"
        "/faz7_status - FAZ-7.9 hafıza özeti\n"
        "/faz7_plan - FAZ-7.9 + FAZ-9.x strateji planı\n"
        "/faz7_register - Günlük conf & edge kaydı\n\n"
        "— <b>FAZ-8.x</b> —\n"
        "/faz8_status - FAZ-8.x status\n"
        "/faz8_test - Manuel FAZ-8.x sinyal testi\n"
        "/faz83_test - FAZ-8.3 full pipeline testi\n\n"
        "— <b>FAZ-10</b> —\n"
        "/faz10 - FAZ-10 Stability + HardSync Report\n\n"
        "— <b>FAZ-11 / FAZ-12</b> —\n"
        "/faz11 - Günlük feedback kayıt\n"
        "/faz12 - Auto profile ayarı\n\n"
        "— <b>FAZ-13</b> —\n"
        "/mac - Manual maç input\n"
        "/mac_api - API simülasyon input\n"
        "/mac_img - Görsel + text kombinasyonu\n"
    )
    bot.reply_to(message, text)


@bot.message_handler(commands=["status"])
def cmd_status(message):
    info = faz79_brain()
    text = (
        "✅ Bot çalışıyor.\n"
        "Mod: <b>Fly.io + Webhook + Flask</b>\n"
        f"ENGINEERING_MODE: <b>{'ON' if ENGINEERING_MODE else 'OFF'}</b>\n"
        "FAZ-7.9 v2.0 hafıza motoru: <b>AKTİF</b>\n"
        "FAZ-9.1/9.2 behavior motoru: <b>AKTİF</b>\n"
        "FAZ-8.2 kalibrasyon: <b>AKTİF</b>\n"
        "FAZ-8.3 full pipeline: <b>AKTİF</b>\n"
        "FAZ-8.4 kupon motoru: <b>AKTİF</b>\n"
        "FAZ-8.5 META profile: <b>AKTİF</b>\n"
        f"Strateji Modu: <b>{info['mode']}</b> | "
        f"Trend: {info['trend']} | Vol: {info['vol']}\n"
        f"TCI: {info['tci']} | Noise: {info['noise_ratio']} | "
        f"BehaviorIndex: {info['behavior_index']}\n"
        f"Hafıza dosyası: <code>{MEMORY_FILE}</code>\n"
    )
    bot.reply_to(message, text)


@bot.message_handler(commands=["faz11"])
def cmd_faz11(message):
    try:
        parts = message.text.split()[1:]
        if not parts:
            bot.reply_to(message, "⚠️ Kullanım: /faz11 1 0 1 1")
            return

        real_results = []
        for p in parts:
            if p in ["1", "true", "True"]:
                real_results.append(True)
            elif p in ["0", "false", "False"]:
                real_results.append(False)

        predicted = [{"conf": 0.60, "edge": 0.03, "bucket": "MID"} for _ in real_results]

        result = _faz11_register_feedback(real_results, predicted)

        text = (
            "🔥 <b>FAZ-11 Günlük Feedback Kaydedildi</b>\n"
            f"Toplam: <b>{result.get('total')}</b>\n"
            f"Doğru: <b>{result.get('correct')}</b>\n"
            f"Accuracy: <b>{result.get('daily_accuracy')}</b>\n"
            f"Avg Conf: <b>{result.get('avg_conf')}</b>\n"
            f"Drift: <b>{result.get('model_drift')}</b>\n"
        )

        bot.reply_to(message, text, parse_mode="HTML")

    except Exception as e:
        log.error(f"[FAZ-11 CMD Error] {e}", exc_info=True)
        bot.reply_to(message, f"❌ FAZ-11 hata: {e}")


@bot.message_handler(commands=["faz12"])
def cmd_faz12(message):
    try:
        brain = faz79_brain()
        f10 = faz10_stability_check(brain)

        f11 = faz11_last_summary()
        if not f11["last"]:
            bot.reply_to(message, "⚠️ FAZ-11 geçmişi bulunamadı.")
            return
        f11_last = f11["last"]

        decision = _faz12_autoadjust(f10, f11_last)

        txt = (
            "🔧 <b>FAZ-12 Auto Profile</b>\n"
            f"Önceki Mod: <b>{decision.get('prev_mode')}</b>\n"
            f"Yeni Mod: <b>{decision.get('new_mode')}</b>\n"
            f"Değişti mi?: <b>{decision.get('changed')}</b>\n"
            f"Neden: <b>{decision.get('reason')}</b>\n"
        )

        bot.reply_to(message, txt, parse_mode="HTML")

    except Exception as e:
        log.error(f"[FAZ-12 CMD Error] {e}", exc_info=True)
        bot.reply_to(message, f"❌ FAZ-12 hata: {e}")


@bot.message_handler(commands=["faz10"])
def cmd_faz10(message):
    try:
        brain = faz79_brain()
        hs = faz10_hardsync(brain)
        result = hs.get("stability", {}) or {}

        reply = (
            "🔥 <b>FAZ-10 Stability Report + HardSync</b>\n\n"
            f"Stability Score: <b>{result.get('stability_score', '-')}</b>\n"
            f"Regime: <b>{result.get('regime', '-')}</b>\n"
            f"Suggested Mode: <b>{result.get('suggested_mode', '-')}</b>\n"
            f"Anomaly Level: <b>{result.get('anomaly_level', '-')}</b>\n"
            f"Trend Slope: <b>{result.get('trend_slope', '-')}</b>\n\n"
            f"HardSync Mode: <b>{hs.get('mode', brain.get('mode', 'INIT'))}</b>\n"
            f"HardSync Bucket: <b>{hs.get('bucket', 'MID')}</b>\n"
            f"HardSync Reason: <b>{hs.get('lock_reason', 'NO_LOCK')}</b>\n"
            f"Engineering Mode: <b>{'ON' if ENGINEERING_MODE else 'OFF'}</b>\n"
        )

        extra = (
            result.get("notes")
            or result.get("explanation")
            or hs.get("stability", {}).get("notes")
        )
        if extra:
            reply += f"\n📝 Notlar: {extra}"

        bot.reply_to(message, reply)
    except Exception as e:
        log.error(f"[FAZ-10] Stability/HardSync hatası: {e}", exc_info=True)
        bot.reply_to(message, f"❌ FAZ-10 stability / HardSync hatası: {e}")


# ================================================================
# 🖼 FAZ-13 VISUAL / MANUAL / API KOMUTLARI
# ================================================================
@bot.message_handler(commands=["mac"])
def cmd_manual_match(message):
    """
    Örnek kullanım:
        /mac BOS ORL 220.5 U 1.46
    """
    try:
        fusion_input = normalize_manual_text(message.text, default_league="NBA")
        text = run_faz13_auto_pipeline(fusion_input)
        bot.reply_to(message, text)
    except Exception as e:
        log.error(f"[FAZ-13 MANUAL] Hata: {e}", exc_info=True)
        bot.reply_to(
            message,
            "❌ FAZ-13 manual input işlenemedi.\n"
            "Format örneği: /mac BOS ORL 220.5 U 1.46",
        )


@bot.message_handler(commands=["mac_api"])
def cmd_api_match(message):
    """
    Demo: API'den gelmiş gibi davranan örnek.
    Sonra gerçek data_fetcher sonucunu buraya koyarsın.
    """
    try:
        dummy_api_data = {
            "league": "NBA",
            "home": "BOS",
            "away": "ORL",
            "market": "total_points",
            "line": 220.5,
            "side": "OVER",
            "odds": 1.46,
        }
        fusion_input = normalize_api_data(dummy_api_data)
        text = run_faz13_auto_pipeline(fusion_input)
        bot.reply_to(message, text)
    except Exception as e:
        log.error(f"[FAZ-13 API] Hata: {e}", exc_info=True)
        bot.reply_to(message, "❌ FAZ-13 API input işlenemedi.")


@bot.message_handler(content_types=["photo"])
def cmd_visual_upload_raw(message):
    try:
        file_id = message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"

        bot.reply_to(message, f"📸 Görsel alındı!\nURL: {file_url}")
    except Exception as e:
        log.error(f"[FAZ-13 VISUAL-UPLOAD] Hata: {e}", exc_info=True)
        bot.reply_to(message, "❌ Görsel alınamadı.")


@bot.message_handler(commands=["mac_img"])
def cmd_visual_match(message):
    """
    Ekran görüntüsü + text meta için.
    Şimdilik sadece text'i parse ediyoruz; ileride OCR eklenir.
    """
    try:
        fusion_input = normalize_manual_text(message.text, default_league="NBA")
        fusion_input.source = "visual"
        text = run_faz13_auto_pipeline(fusion_input)
        bot.reply_to(message, text)
    except Exception as e:
        log.error(f"[FAZ-13 VISUAL] Hata: {e}", exc_info=True)
        bot.reply_to(
            message,
            "❌ FAZ-13 visual input işlenemedi.\n"
            "Format: /mac_img BOS ORL 220.5 U 1.46 + ekran görüntüsü",
        )


# ================================================================
# 🚀 STARTUP: WEBHOOK AYARLA & FLASK ÇALIŞTIR
# ================================================================
def setup_webhook():
    try:
        log.info("Önce eski webhook kaldırılıyor...")
        bot.delete_webhook()
    except Exception as e:
        log.warning(f"Eski webhook silinirken hata (önemli değil): {e}")

    if WEBHOOK_URL:
        for attempt in range(1, 3):
            try:
                log.info(f"[FAZ-8.x] Webhook deneme {attempt}: {WEBHOOK_URL}")
                bot.set_webhook(url=WEBHOOK_URL)
                log.info("[FAZ-8.x] Webhook başarıyla set edildi.")
                break
            except Exception as e:
                log.error(f"[FAZ-8.x] Webhook set hatası (deneme {attempt}): {e}")
                time.sleep(1.5)
    else:
        log.warning("WEBHOOK_URL tanımlı değil, webhook set edilmedi!")


if __name__ == "__main__":
    log.info(
        "🔥 Boot: FAZ-7.9 + FAZ-8.x + FAZ-6 v3 + FAZ-9.x + FAZ-10 HardSync + FAZ-11 + FAZ-12 + FAZ-13 | ENGINEERING_MODE=%s",
        "ON" if ENGINEERING_MODE else "OFF",
    )
    init_memory()
    setup_webhook()
    port = int(os.getenv("PORT", 8080))
    log.info(f"Flask HTTP server 0.0.0.0:{port} üzerinde çalışıyor.")
    app.run(host="0.0.0.0", port=port)
