import os
import json
import time
import logging

import telebot
import numpy as np
import pandas as pd
from flask import Flask, request

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
        json_update = request.get_json()
        update = telebot.types.Update.de_json(json_update)
        bot.process_new_updates([update])
    except Exception as e:
        log.error(f"Webhook update işlenirken hata: {e}")
    return "OK", 200


# ================================================================
# 📌 FAZ-7.9 v2.0 MEMORY ENGINE
# ================================================================
MEMORY_FILE = "faz7_memory.json"


def init_memory():
    if not os.path.exists(MEMORY_FILE):
        data = {
            "days": [],
            "safe": 0,
            "bal": 0,
            "agg": 0,
        }
        with open(MEMORY_FILE, "w") as f:
            json.dump(data, f, indent=4)


def load_memory():
    init_memory()
    with open(MEMORY_FILE, "r") as f:
        return json.load(f)


def save_memory(data):
    with open(MEMORY_FILE, "w") as f:
        json.dump(data, f, indent=4)


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


def _ema(series: pd.Series, alpha: float = 0.6) -> float:
    if len(series) == 0:
        return 0.0
    ema_val = series.iloc[0]
    for x in series.iloc[1:]:
        ema_val = alpha * x + (1 - alpha) * ema_val
    return float(ema_val)


def faz79_brain():
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
        log.warning(f"FAZ-7.9 slope hesap hatası: {e}")
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
        "stake_norm": 1.00,
        "safe": mode == "SAFE",
        "bal": mode == "BAL",
        "agg": mode == "AGG",
    }


# ================================================================
# 🧠 FAZ-8.1 CORE CALIBRATION ENGINE
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
    else:
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


# ================================================================
# 🧠 FAZ-8.2 LMF SHIELD
# ================================================================
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


# ================================================================
# 🧠 FAZ-8.3 DYNAMIC CALIBRATION ENGINE
# ================================================================
def faz83_compute_risk_bucket(conf: float,
                              edge: float,
                              conf_avg: float,
                              edge_avg: float) -> tuple[str, float]:

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

    base_mult_map = {
        "LOW": 0.70,
        "MID": 0.90,
        "HIGH": 1.10,
    }
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
# 🧠 FAZ-8.4 — COUPON ENGINE
# ================================================================
def faz84_coupon_engine(profile: str,
                        raw_conf: float,
                        raw_edge: float,
                        base_stake: float = 1.0) -> dict:

    core = _faz81_core_calibration(raw_conf, raw_edge, base_stake)
    core82 = _faz82_lmf_shield(core)

    brain = faz79_brain()
    conf_avg = brain["conf"] if brain["conf"] > 0 else max(raw_conf, 0.01)
    edge_avg = brain["edge"] if brain["edge"] > 0 else max(raw_edge, 0.01)

    c83 = faz83_dynamic_calibration(
        conf=core82["conf"],
        edge=core82["edge"],
        stake=core82["stake"],
        mode=brain["mode"],
        trend_slope=brain["slope"],
        vol=brain["vol"],
        conf_avg=conf_avg,
        edge_avg=edge_avg,
    )

    conf = c83["cal_conf"]
    edge = c83["cal_edge"]
    stake = c83["cal_stake"]
    bucket = c83["bucket"]

    profile = (profile or "BAL").upper()
    if profile == "SAFE":
        stake *= 0.85
        conf = min(0.99, conf + 0.02)
    elif profile == "BAL":
        stake *= 1.00
    elif profile == "AGG":
        stake *= 1.12
        conf = max(0.0, conf - 0.01)
    elif profile == "ULTRA":
        stake *= 1.20
        conf = max(0.0, conf - 0.02)

    if bucket == "HIGH" and conf >= 0.67:
        risk_label = "HIGH"
    elif bucket == "LOW" or conf < 0.58:
        risk_label = "LOW"
    else:
        risk_label = "MID"

    stake = round(max(0.1, stake), 2)
    conf = round(max(0.0, min(conf, 0.99)), 2)
    edge = round(max(0.0, edge), 3)

    return {
        "mode": brain["mode"],
        "trend": brain["trend"],
        "bucket": bucket,
        "risk": risk_label,
        "conf": conf,
        "edge": edge,
        "stake": stake,
    }


# ================================================================
# 🧠 PUBLIC FAZ-8 API
# ================================================================
def faz8_calibrate_signal(raw_conf: float,
                          raw_edge: float,
                          base_stake: float = 1.0) -> dict:

    core = _faz81_core_calibration(raw_conf, raw_edge, base_stake)
    brain = faz79_brain()

    conf_avg = brain["conf"] if brain["conf"] > 0 else max(raw_conf, 0.01)
    edge_avg = brain["edge"] if brain["edge"] > 0 else max(raw_edge, 0.01)

    core82 = _faz82_lmf_shield(core)
    c83 = faz83_dynamic_calibration(
        conf=core82["conf"],
        edge=core82["edge"],
        stake=core82["stake"],
        mode=brain["mode"],
        trend_slope=brain["slope"],
        vol=brain["vol"],
        conf_avg=conf_avg,
        edge_avg=edge_avg,
    )

    return {
        "engine": "FAZ-8.3",
        "mode": brain["mode"],
        "trend": brain["trend"],
        "vol": brain["vol"],
        "bucket": c83["bucket"],
        "score": c83["score"],
        "conf": c83["cal_conf"],
        "edge": c83["cal_edge"],
        "stake": c83["cal_stake"],
    }


# ================================================================
# 🏀 FAZ-6 → KUPON & SİMÜLASYON (FAZ-8.4 MOTORU)
# ================================================================
def _faz84_from_raw(profile: str,
                    raw_conf: float,
                    raw_edge: float,
                    base_stake: float) -> dict:
    return faz84_coupon_engine(profile, raw_conf, raw_edge, base_stake)


def build_faz6_coupons_text():

    k1_g1 = _faz84_from_raw("SAFE", 0.66, 0.045, 0.88)
    k1_g2 = _faz84_from_raw("SAFE", 0.64, 0.041, 0.84)

    k2_g1 = _faz84_from_raw("BAL", 0.63, 0.036, 0.80)
    k2_g2 = _faz84_from_raw("BAL", 0.61, 0.032, 0.76)

    k3_g1 = _faz84_from_raw("AGG", 0.60, 0.031, 0.75)

    k4_g1 = _faz84_from_raw("ULTRA", 0.59, 0.028, 0.73)

    def fmt(game, calib):
        return (
            f"{game}\n"
            f"  Güven: {calib['conf']:.2f} | "
            f"Edge: {calib['edge']:.3f} | "
            f"Stake: {calib['stake']:.2f} | "
            f"Risk: {calib['risk']} | Mode: {calib['mode']}\n"
        )

    return (
        "🔥 <b>FAZ-6 KUPONLARI (FAZ-8.4 Kupon Motoru)</b>\n\n"
        "🔥 <b>Kupon 1 — SAFE</b>\n" +
        fmt("- EL:EFES@REAL | REAL MADRID -5.5", k1_g1) +
        fmt("- EL:FENER@OLY | OLY -3.5", k1_g2) +
        f"💰 Toplam Stake: {k1_g1['stake'] + k1_g2['stake']:.2f}\n"
        "— — —\n\n"
        "🔥 <b>Kupon 2 — BALANCED</b>\n" +
        fmt("- NBA:BOS@MIA | UNDER 224.5", k2_g1) +
        fmt("- NBA:LAL@DEN | DEN -4.5", k2_g2) +
        f"💰 Toplam Stake: {k2_g1['stake'] + k2_g2['stake']:.2f}\n"
        "— — —\n\n"
        "🔥 <b>Kupon 3 — AGGRESSIVE</b>\n" +
        fmt("- NBA:CHI@NYK | NYK ML", k3_g1) +
        f"💰 Toplam Stake: {k3_g1['stake']:.2f}\n"
        "— — —\n\n"
        "🔥 <b>Kupon 4 — ULTRA</b>\n" +
        fmt("- NBA:GSW@PHX | OVER 230.5", k4_g1) +
        f"💰 Toplam Stake: {k4_g1['stake']:.2f}\n"
    )


@bot.message_handler(commands=["faz6_coupon"])
def faz6_coupon(message):
    bot.reply_to(message, build_faz6_coupons_text())


# ================================================================
# 🏀 NBA SİMÜLASYON (FAZ-8.4)
# ================================================================
def build_nba_simulation_text():

    home = "MIA"
    away = "NYK"

    skor = 104
    tempo = 98.8

    raw_conf = 0.62
    raw_edge = 0.034

    c = faz84_coupon_engine("BAL", raw_conf, raw_edge, base_stake=1.0)

    win_team = home
    win_prob = c["conf"]

    risk_label = {
        "SAFE": "🛡 SAFE",
        "BAL": "⚖ BALANCED",
        "AGG": "⚡ AGGRESSIVE",
        "INIT": "⏳ INIT",
    }.get(c["mode"], c["mode"])

    return (
        "🏀 <b>NBA Simülasyon (FAZ-8.4)</b>\n\n"
        f"{home} vs {away}\n"
        f"📈 Skor Tahmini: <b>{skor}</b>\n"
        f"⏱ Tempo: <b>{tempo}</b>\n"
        f"🎯 Kazanan: <b>{win_team}</b> ({int(win_prob * 100)}%)\n"
        f"📊 Risk: {risk_label} | Bucket: <b>{c['bucket']}</b>\n"
        f"🔍 Edge: {c['edge']:.3f}\n"
        f"💰 Stake: {c['stake']:.2f}\n"
    )


@bot.message_handler(commands=["simulate_nba"])
def cmd_simulate_nba(message):
    try:
        bot.reply_to(message, "🏀 Simülasyon başlatılıyor...")
        bot.reply_to(message, build_nba_simulation_text())
    except Exception as e:
        bot.reply_to(message, f"❌ Simülasyon hatası: {e}")


# ================================================================
# 🧰 FAZ-6 Placeholders
# ================================================================
@bot.message_handler(commands=["faz6_test"])
def faz6_test(message):
    bot.reply_to(message, "🧪 FAZ-6 Test modu.")


@bot.message_handler(commands=["faz6_auto"])
def faz6_auto(message):
    bot.reply_to(message, "🤖 FAZ-6 Auto modu.")


@bot.message_handler(commands=["faz6_risk"])
def faz6_risk(message):
    bot.reply_to(message, "⚠️ FAZ-6 Risk modu.")


@bot.message_handler(commands=["faz6_edge"])
def faz6_edge(message):
    bot.reply_to(message, "📐 FAZ-6 Edge modu.")


@bot.message_handler(commands=["faz6_real"])
def faz6_real(message):
    bot.reply_to(message, "📊 FAZ-6 Real modu.")


@bot.message_handler(commands=["faz6_balance"])
def faz6_balance(message):
    bot.reply_to(message, "⚖️ FAZ-6 Balance modu.")


# ================================================================
# 🧰 GENEL KOMUTLAR
# ================================================================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    bot.reply_to(
        message,
        "🔥 <b>Bot aktif!</b>\nFAZ-6 + FAZ-7.9 + FAZ-8.x + FAZ-8.4 bağlı.\n"
        "Komutlar: /help"
    )


@bot.message_handler(commands=["help"])
def cmd_help(message):
    bot.reply_to(
        message,
        "📌 <b>Komutlar</b>\n\n"
        "/start\n"
        "/status\n"
        "/simulate_nba\n"
        "/faz6_coupon\n"
        "/faz7_status\n"
        "/faz7_plan\n"
        "/faz7_register\n"
        "/faz8_status\n"
        "/faz8_test\n"
        "/faz83_test\n"
    )


@bot.message_handler(commands=["status"])
def cmd_status(message):
    info = faz79_brain()
    bot.reply_to(
        message,
        f"✅ Bot çalışıyor.\n"
        f"Mod: {info['mode']} | Trend: {info['trend']} | Vol: {info['vol']}"
    )


# ================================================================
# 🚀 STARTUP (WEBHOOK + FLASK)
# ================================================================
def setup_webhook():
    try:
        bot.delete_webhook()
    except:
        pass

    if WEBHOOK_URL:
        for attempt in range(1, 3):
            try:
                log.info(f"[FAZ-8.4] Webhook set deneme {attempt}: {WEBHOOK_URL}")
                bot.set_webhook(url=WEBHOOK_URL)
                log.info("[FAZ-8.4] Webhook başarıyla set edildi.")
                break
            except Exception as e:
                log.error(f"[FAZ-8.4] Webhook set hatası: {e}")
                time.sleep(1.5)
    else:
        log.warning("WEBHOOK_URL tanımlı değil!")


if __name__ == "__main__":
    init_memory()
    setup_webhook()
    port = int(os.getenv("PORT", 8080))
    log.info(f"Flask server 0.0.0.0:{port} üzerinde çalışıyor.")
    app.run(host="0.0.0.0", port=port)
