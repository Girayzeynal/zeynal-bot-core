import os
import json
import time
import logging

import telebot
import numpy as np
import pandas as pd
from flask import Flask, request

# ================================================================
# LOGGING
# ================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# ================================================================
# CONFIG
# ================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # e.g. https://zeynal-bot-core.fly.dev/webhook

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env tanımlı değil!")

if not WEBHOOK_URL:
    log.warning("WEBHOOK_URL yok → webhook set edilmeyecek!")

bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode="HTML",
    disable_web_page_preview=True
)

# ================================================================
# FLASK APP
# ================================================================
app = Flask(__name__)


@app.route("/", methods=["GET"])
def home():
    return "OK", 200


@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    try:
        data = request.get_json()
        update = telebot.types.Update.de_json(data)
        bot.process_new_updates([update])
    except Exception as e:
        log.error(f"Webhook update hatası: {e}")
    return "OK", 200


# ================================================================
# FAZ-7.9 MEMORY ENGINE
# ================================================================
MEMORY_FILE = "faz7_memory.json"


def init_memory():
    if not os.path.exists(MEMORY_FILE):
        struct = {
            "days": [],
            "safe": 0,
            "bal": 0,
            "agg": 0
        }
        with open(MEMORY_FILE, "w") as f:
            json.dump(struct, f, indent=4)


def load_memory():
    init_memory()
    with open(MEMORY_FILE, "r") as f:
        return json.load(f)


def save_memory(mem):
    with open(MEMORY_FILE, "w") as f:
        json.dump(mem, f, indent=4)


def register_daily_stats(conf, edge):
    mem = load_memory()
    entry = {
        "ts": int(time.time()),
        "conf": float(conf),
        "edge": float(edge)
    }
    mem["days"].append(entry)
    if len(mem["days"]) > 7:
        mem["days"] = mem["days"][-7:]
    save_memory(mem)


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
            "stake_norm": 1.0,
            "safe": False,
            "bal": True,
            "agg": False
        }

    df = pd.DataFrame(days)
    df["t"] = range(len(df))

    avg_conf = float(df["conf"].mean())
    avg_edge = float(df["edge"].mean())

    try:
        slope = float(np.polyfit(df["t"], df["conf"], 1)[0])
    except Exception as e:
        log.warning(f"FAZ-7.9 slope hesaplanırken hata: {e}")
        slope = 0.0

    if slope > 0.01:
        trend = "UP"
    elif slope < -0.01:
        trend = "DOWN"
    else:
        trend = "FLAT"

    vol = float(df["conf"].std() if len(df) > 1 else 0.0)

    if avg_conf > 0.7 and avg_edge > 0.05:
        mode = "SAFE"
    elif avg_conf > 0.4:
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
        "stake_norm": 1.0,
        "safe": mode == "SAFE",
        "bal": mode == "BAL",
        "agg": mode == "AGG"
    }


# ================================================================
# FAZ-8.1 CORE ENGINE
# ================================================================
def _faz81_core_calibration(raw_conf, raw_edge, base_stake):
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
            "stake": round(stake, 2)
        }

    if mode == "SAFE":
        stake_factor = 0.90
        conf_boost = 0.03
    elif mode == "BAL":
        stake_factor = 1.00
        conf_boost = 0.00
    else:  # AGG
        stake_factor = 1.15
        conf_boost = -0.02

    if trend == "UP":
        conf += 0.02
        edge *= 1.05
    elif trend == "DOWN":
        conf -= 0.02
        edge *= 0.95

    if vol > 0.15:
        conf -= 0.02
        stake_factor *= 0.92
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
        "stake": round(stake, 2)
    }


# ================================================================
# FAZ-8.2 LMF SHIELD
# ================================================================
def _faz82_lmf_shield(calib):
    mode = calib.get("mode", "BAL")
    trend = calib.get("trend", "INIT")
    vol = float(calib.get("vol", 0.0))
    conf = float(calib.get("conf", 0.0))
    edge = float(calib.get("edge", 0.0))
    stake = float(calib.get("stake", 1.0))

    profiles = {
        "SAFE": {
            "edge_floor": 0.030,
            "edge_hard": 0.020,
            "vsoft": 0.08,
            "vhard": 0.18,
            "upf": 1.05,
            "downf": 0.88
        },
        "BAL": {
            "edge_floor": 0.028,
            "edge_hard": 0.018,
            "vsoft": 0.10,
            "vhard": 0.22,
            "upf": 1.04,
            "downf": 0.90
        },
        "AGG": {
            "edge_floor": 0.025,
            "edge_hard": 0.015,
            "vsoft": 0.12,
            "vhard": 0.26,
            "upf": 1.03,
            "downf": 0.92
        }
    }

    prof = profiles.get(mode, profiles["BAL"])

    if edge < prof["edge_hard"]:
        stake *= 0.45
        conf *= 0.80
    elif edge < prof["edge_floor"]:
        stake *= 0.70
        conf *= 0.90

    if vol > prof["vhard"]:
        stake *= 0.65
        conf *= 0.90
    elif vol > prof["vsoft"]:
        stake *= 0.80
        conf *= 0.95

    if trend == "DOWN":
        stake *= prof["downf"]
        conf *= prof["downf"]
    elif trend == "UP":
        stake *= prof["upf"]
        conf *= prof["upf"]

    conf = max(0.0, min(conf, 0.99))
    edge = max(0.0, edge)
    stake = max(0.1, stake)

    calib["engine"] = "FAZ-8.2"
    calib["conf"] = round(conf, 3)
    calib["edge"] = round(edge, 3)
    calib["stake"] = round(stake, 2)
    return calib


# ================================================================
# FAZ-8.3 DYNAMIC CALIBRATION ENGINE (FULL)
# ================================================================
def faz83_compute_risk_bucket(conf, edge, conf_avg, edge_avg):
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


def faz83_dynamic_calibration(conf,
                              edge,
                              stake,
                              mode,
                              trend_slope,
                              vol,
                              conf_avg,
                              edge_avg):
    bucket, score = faz83_compute_risk_bucket(conf, edge, conf_avg, edge_avg)

    base_mult_map = {
        "LOW": 0.70,
        "MID": 0.90,
        "HIGH": 1.10
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
        "cal_stake": cal_stake
    }


# ================================================================
# FAZ-8.x PUBLIC API (8.1 + 8.2 + 8.3)
# ================================================================
def faz8_calibrate_signal(raw_conf, raw_edge, base_stake=1.0):
    c81 = _faz81_core_calibration(raw_conf, raw_edge, base_stake)
    if c81["mode"] not in ("SAFE", "BAL", "AGG"):
        c81["engine"] = "FAZ-8.3"
        return c81

    c82 = _faz82_lmf_shield(c81)

    brain = faz79_brain()
    conf_avg = brain["conf"] if brain["conf"] > 0 else max(raw_conf, 0.01)
    edge_avg = brain["edge"] if brain["edge"] > 0 else max(raw_edge, 0.01)

    c83 = faz83_dynamic_calibration(
        conf=c82["conf"],
        edge=c82["edge"],
        stake=c82["stake"],
        mode=brain["mode"],
        trend_slope=brain["slope"],
        vol=brain["vol"],
        conf_avg=conf_avg,
        edge_avg=edge_avg
    )

    return c83


def faz83_from_raw(raw_conf, raw_edge, base_stake=1.0):
    c = faz8_calibrate_signal(raw_conf, raw_edge, base_stake)
    brain = faz79_brain()
    return {
        "mode": brain["mode"],
        "trend": brain["trend"],
        "bucket": c.get("bucket", "MID"),
        "conf": c.get("cal_conf", c.get("conf", raw_conf)),
        "edge": c.get("cal_edge", c.get("edge", raw_edge)),
        "stake": c.get("cal_stake", c.get("stake", base_stake))
    }


# ================================================================
# FAZ-8.4 COUPON ENGINE
# ================================================================
def faz84_build_coupon(matches, profile_name):
    """
    matches: [{code, conf, edge, stake}, ...]
    profile_name: SAFE / BAL / AGG / ULTRA
    """
    profile_name = (profile_name or "BAL").upper()

    profile_mult = {
        "SAFE": 0.85,
        "BAL": 1.00,
        "AGG": 1.10,
        "ULTRA": 1.20
    }.get(profile_name, 1.00)

    out = []
    total_stake = 0.0

    for m in matches:
        cal = faz83_from_raw(m["conf"], m["edge"], m["stake"])
        stake = round(cal["stake"] * profile_mult, 2)
        total_stake += stake

        out.append({
            "code": m["code"],
            "conf": cal["conf"],
            "edge": cal["edge"],
            "stake": stake,
            "bucket": cal["bucket"],
            "mode": cal["mode"],
            "trend": cal["trend"]
        })

    return out, round(total_stake, 2), profile_name


# ================================================================
# TELEGRAM KOMUTLARI – FAZ-7.9
# ================================================================
@bot.message_handler(commands=["faz7_status"])
def cmd_faz7_status(message):
    mem = load_memory()
    if len(mem["days"]) == 0:
        bot.reply_to(message, "📊 <b>FAZ-7.9 hafıza boş.</b>")
        return

    df = pd.DataFrame(mem["days"])
    msg = (
        "📊 <b>FAZ-7.9 HAFIZA ÖZETİ</b>\n\n"
        f"SAFE: {mem['safe']}\n"
        f"BAL : {mem['bal']}\n"
        f"AGG : {mem['agg']}\n\n"
        f"7g Avg Conf: <b>{df['conf'].mean():.3f}</b>\n"
        f"7g Avg Edge: <b>{df['edge'].mean():.3f}</b>"
    )
    bot.reply_to(message, msg)


@bot.message_handler(commands=["faz7_plan"])
def cmd_faz7_plan(message):
    info = faz79_brain()
    msg = (
        "🧠 <b>FAZ-7.9 STRATEJİ BEYNİ</b>\n\n"
        f"Mod: <b>{info['mode']}</b>\n"
        f"Trend: {info['trend']} (slope {info['slope']})\n"
        f"Vol: {info['vol']}\n"
        f"Conf: {info['conf']} | Edge: {info['edge']}\n"
        f"Stake Norm: {info['stake_norm']}\n"
    )
    bot.reply_to(message, msg)


@bot.message_handler(commands=["faz7_register"])
def cmd_faz7_register(message):
    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(
            message,
            "Kullanım: /faz7_register conf edge\n"
            "Örnek: /faz7_register 0.62 0.035"
        )
        return

    try:
        c = float(parts[1])
        e = float(parts[2])
    except ValueError:
        bot.reply_to(message, "conf ve edge sayısal olmalı.")
        return

    register_daily_stats(c, e)
    info = faz79_brain()
    bot.reply_to(
        message,
        f"✅ Kayıt alındı.\n"
        f"Yeni Mod: {info['mode']} | Trend: {info['trend']} | Vol: {info['vol']}"
    )


# ================================================================
# TELEGRAM KOMUTLARI – FAZ-8.x
# ================================================================
@bot.message_handler(commands=["faz8_status"])
def cmd_faz8_status(message):
    raw_conf = 0.64
    raw_edge = 0.038
    calib = faz8_calibrate_signal(raw_conf, raw_edge, 1.0)

    bot.reply_to(
        message,
        "🧪 <b>FAZ-8.3 STATUS</b>\n\n"
        f"Mode: {calib.get('mode')}\n"
        f"Trend: {calib.get('trend')} | Vol: {calib.get('vol')}\n"
        f"Engine: {calib.get('engine')}\n"
        f"Final → Conf={calib.get('cal_conf', calib.get('conf'))} "
        f"Edge={calib.get('cal_edge', calib.get('edge'))} "
        f"Stake={calib.get('cal_stake', calib.get('stake'))}"
    )


@bot.message_handler(commands=["faz8_test"])
def cmd_faz8_test(message):
    parts = message.text.split()
    if len(parts) not in (3, 4):
        bot.reply_to(message, "Kullanım: /faz8_test conf edge [stake]")
        return

    try:
        conf = float(parts[1])
        edge = float(parts[2])
        stake = float(parts[3]) if len(parts) == 4 else 1.0
    except ValueError:
        bot.reply_to(message, "conf, edge, stake sayısal olmalı.")
        return

    calib = faz8_calibrate_signal(conf, edge, stake)

    bot.reply_to(
        message,
        "🧪 <b>FAZ-8.3 TEST</b>\n\n"
        f"Mode={calib.get('mode')} Trend={calib.get('trend')} Vol={calib.get('vol')}\n"
        f"Engine={calib.get('engine')}\n"
        f"Conf={calib.get('cal_conf', calib.get('conf'))} "
        f"Edge={calib.get('cal_edge', calib.get('edge'))} "
        f"Stake={calib.get('cal_stake', calib.get('stake'))}"
    )


@bot.message_handler(commands=["faz83_test"])
def cmd_faz83_test(message):
    parts = message.text.split()
    if len(parts) not in (3, 4):
        bot.reply_to(
            message,
            "Kullanım: /faz83_test conf edge [stake]\n"
            "Örnek: /faz83_test 0.63 0.035 0.80"
        )
        return

    try:
        raw_conf = float(parts[1])
        raw_edge = float(parts[2])
        base_stake = float(parts[3]) if len(parts) == 4 else 1.0
    except ValueError:
        bot.reply_to(message, "conf, edge, stake sayısal olmalı.")
        return

    calib = faz8_calibrate_signal(raw_conf, raw_edge, base_stake)
    brain = faz79_brain()

    bot.reply_to(
        message,
        "🧪 <b>FAZ-8.3 FULL PIPELINE</b>\n\n"
        f"Input RAW → conf={raw_conf:.3f}, edge={raw_edge:.3f}, stake={base_stake:.2f}\n\n"
        f"FAZ-7.9 → mode={brain['mode']}, trend={brain['trend']} "
        f"(slope {brain['slope']}), vol={brain['vol']}\n"
        f"7g avg → conf={brain['conf']}, edge={brain['edge']}\n\n"
        f"FAZ-8.x → engine={calib.get('engine')}, bucket={calib.get('bucket','-')}\n"
        f"Calibrated → conf={calib.get('cal_conf', calib.get('conf'))} "
        f"edge={calib.get('cal_edge', calib.get('edge'))} "
        f"stake={calib.get('cal_stake', calib.get('stake'))}\n"
    )


# ================================================================
# TELEGRAM KOMUTLARI – FAZ-8.4 KUPON MOTORU
# ================================================================
def _fmt_coupon_line(game, row):
    return (
        f"{game}\n"
        f"  Güven: {row['conf']:.2f} | "
        f"Edge: {row['edge']:.3f} | "
        f"Stake: {row['stake']:.2f} | "
        f"Risk: {row['bucket']} | "
        f"Mode: {row['mode']}\n"
    )


def build_faz6_coupons_text():
    # Kupon 1 – SAFE profile
    k1_matches = [
        {"code": "- EL:EFES@REAL | REAL MADRID -5.5 (spread)", "conf": 0.66, "edge": 0.045, "stake": 0.88},
        {"code": "- EL:FENER@OLY | OLYMPIACOS -3.5 (spread)", "conf": 0.64, "edge": 0.041, "stake": 0.84},
    ]
    k1_rows, k1_total, k1_prof = faz84_build_coupon(k1_matches, "SAFE")

    # Kupon 2 – BAL profile
    k2_matches = [
        {"code": "- NBA:BOS@MIA | UNDER 224.5 (total)", "conf": 0.63, "edge": 0.036, "stake": 0.80},
        {"code": "- NBA:LAL@DEN | DEN -4.5 (spread)", "conf": 0.61, "edge": 0.032, "stake": 0.76},
    ]
    k2_rows, k2_total, k2_prof = faz84_build_coupon(k2_matches, "BAL")

    # Kupon 3 – AGG profile
    k3_matches = [
        {"code": "- NBA:CHI@NYK | NYK ML (moneyline)", "conf": 0.60, "edge": 0.031, "stake": 0.75},
    ]
    k3_rows, k3_total, k3_prof = faz84_build_coupon(k3_matches, "AGG")

    # Kupon 4 – ULTRA profile
    k4_matches = [
        {"code": "- NBA:GSW@PHX | OVER 230.5 (total)", "conf": 0.59, "edge": 0.028, "stake": 0.73},
    ]
    k4_rows, k4_total, k4_prof = faz84_build_coupon(k4_matches, "ULTRA")

    text = "🔥 <b>FAZ-6 KUPONLARI (FAZ-8.4 Kupon Motoru)</b>\n\n"

    text += f"🔥 <b>Kupon 1 — SAFE [{k1_prof}]</b>\n"
    for r in k1_rows:
        text += _fmt_coupon_line(r["code"], r)
    text += f"💰 Toplam Stake: {k1_total:.2f}\n— — —\n\n"

    text += f"🔥 <b>Kupon 2 — BALANCED [{k2_prof}]</b>\n"
    for r in k2_rows:
        text += _fmt_coupon_line(r["code"], r)
    text += f"💰 Toplam Stake: {k2_total:.2f}\n— — —\n\n"

    text += f"🔥 <b>Kupon 3 — AGGRESSIVE [{k3_prof}]</b>\n"
    for r in k3_rows:
        text += _fmt_coupon_line(r["code"], r)
    text += f"💰 Toplam Stake: {k3_total:.2f}\n— — —\n\n"

    text += f"🔥 <b>Kupon 4 — ULTRA [{k4_prof}]</b>\n"
    for r in k4_rows:
        text += _fmt_coupon_line(r["code"], r)
    text += f"💰 Toplam Stake: {k4_total:.2f}\n"

    return text


@bot.message_handler(commands=["faz6_coupon"])
def cmd_faz6_coupon(message):
    text = build_faz6_coupons_text()
    bot.reply_to(message, text)


# ================================================================
# TELEGRAM KOMUTLARI – NBA SİMÜLASYON
# ================================================================
def build_nba_simulation_text():
    home = "MIA"
    away = "NYK"
    skor = 104
    tempo = 98.8
    pace = 98.8

    raw_conf = 0.62
    raw_edge = 0.034

    c = faz83_from_raw(raw_conf, raw_edge, base_stake=1.0)

    win_team = home
    win_prob = c["conf"]

    risk_label = {
        "SAFE": "🛡 SAFE",
        "BAL": "⚖ BALANCED",
        "AGG": "⚡ AGGRESSIVE",
        "INIT": "⏳ INIT"
    }.get(c["mode"], c["mode"])

    return (
        "🏀 <b>NBA Simülasyon Sonuçları (FAZ-8.4 Pipeline)</b>\n\n"
        f"🏠 {home} vs ✈️ {away}\n"
        f"📈 Tahmini Skor: <b>{skor}</b>\n"
        f"⏱ Tempo: <b>{tempo}</b>\n"
        f"🎯 Kazanan: <b>{win_team}</b> ({int(win_prob * 100)}%)\n"
        f"📊 Risk Profili: {risk_label} | Bucket: <b>{c['bucket']}</b>\n"
        f"🔍 Edge: <b>{c['edge']:.3f}</b>\n"
        f"💰 Stake: <b>{c['stake']:.2f}</b>\n\n"
        "🧠 <b>Ham Analiz</b>:\n"
        "🔥 <b>NBA – Canlı Maçlar</b>\n"
        f"🏀 {home} (54) – {away} (50)\n"
        f"⏱ Pace Tahmini: <b>{pace}</b>"
    )


@bot.message_handler(commands=["simulate_nba"])
def cmd_simulate_nba(message):
    try:
        bot.reply_to(message, "🏀 Simülasyon başlatılıyor (FAZ-8.4 kupon motoru referanslı)...")
        text = build_nba_simulation_text()
        bot.reply_to(message, text)
    except Exception as e:
        bot.reply_to(message, f"❌ Simülasyon hatası: {e}")


# ================================================================
# DİĞER FAZ-6 PLACEHOLDER KOMUTLARI
# ================================================================
@bot.message_handler(commands=["faz6_test"])
def cmd_faz6_test(message):
    bot.reply_to(message, "🧪 FAZ-6 Test modu placeholder.")


@bot.message_handler(commands=["faz6_auto"])
def cmd_faz6_auto(message):
    bot.reply_to(message, "🤖 FAZ-6 Auto modu placeholder.")


@bot.message_handler(commands=["faz6_risk"])
def cmd_faz6_risk(message):
    bot.reply_to(message, "⚠️ FAZ-6 Risk modu placeholder.")


@bot.message_handler(commands=["faz6_edge"])
def cmd_faz6_edge(message):
    bot.reply_to(message, "📐 FAZ-6 Edge modu placeholder.")


@bot.message_handler(commands=["faz6_real"])
def cmd_faz6_real(message):
    bot.reply_to(message, "📊 FAZ-6 Real modu placeholder.")


@bot.message_handler(commands=["faz6_balance"])
def cmd_faz6_balance(message):
    bot.reply_to(message, "⚖️ FAZ-6 Balance modu placeholder.")


# ================================================================
# GENEL KOMUTLAR
# ================================================================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    text = (
        "🔥 <b>Bot aktif!</b>\n"
        "FAZ-4 + FAZ-5 + FAZ-6 + FAZ-7.9 + FAZ-8.2 + FAZ-8.3 + FAZ-8.4 bağlı.\n"
        "Komut listesi için <code>/help</code> yaz."
    )
    bot.reply_to(message, text)


@bot.message_handler(commands=["help"])
def cmd_help(message):
    text = (
        "📌 <b>Komutlar</b>:\n\n"
        "/start - Botu başlat\n"
        "/help - Komut listesi\n"
        "/status - Sistem durumu\n\n"
        "/simulate_nba - NBA canlı simülasyon (FAZ-8.4)\n\n"
        "— <b>FAZ-6</b> —\n"
        "/faz6_test - FAZ-6 Test\n"
        "/faz6_auto - FAZ-6 Auto\n"
        "/faz6_risk - FAZ-6 Risk\n"
        "/faz6_edge - FAZ-6 Edge\n"
        "/faz6_real - FAZ-6 Real\n"
        "/faz6_balance - FAZ-6 Balance\n"
        "/faz6_coupon - FAZ-6 Kupon (FAZ-8.4 kupon motoru)\n\n"
        "— <b>FAZ-7.9</b> —\n"
        "/faz7_status - FAZ-7.9 hafıza özeti\n"
        "/faz7_plan - FAZ-7.9 strateji planı\n"
        "/faz7_register - Günlük conf & edge kaydı\n\n"
        "— <b>FAZ-8.x</b> —\n"
        "/faz8_status - FAZ-8.x status\n"
        "/faz8_test - Manuel FAZ-8.x sinyal testi\n"
        "/faz83_test - FAZ-8.3 full pipeline testi\n"
    )
    bot.reply_to(message, text)


@bot.message_handler(commands=["status"])
def cmd_status(message):
    info = faz79_brain()
    text = (
        "✅ Bot çalışıyor.\n"
        "Mod: <b>Fly.io + Webhook + Flask</b>\n"
        "FAZ-7.9 hafıza: <b>AKTİF</b>\n"
        "FAZ-8.2 LMF Shield: <b>AKTİF</b>\n"
        "FAZ-8.3 Dynamic Calibration: <b>AKTİF</b>\n"
        "FAZ-8.4 Kupon Motoru: <b>AKTİF</b>\n"
        f"Strateji Modu: <b>{info['mode']}</b> | "
        f"Trend: {info['trend']} | Vol: {info['vol']}\n"
    )
    bot.reply_to(message, text)


# ================================================================
# STARTUP
# ================================================================
def setup_webhook():
    try:
        log.info("Eski webhook kaldırılıyor...")
        bot.delete_webhook()
    except Exception as e:
        log.warning(f"Eski webhook silinirken hata: {e}")

    if WEBHOOK_URL:
        for attempt in range(1, 4):
            try:
                log.info(f"Webhook deneme {attempt}: {WEBHOOK_URL}")
                bot.set_webhook(url=WEBHOOK_URL)
                log.info("Webhook başarıyla set edildi.")
                break
            except Exception as e:
                log.error(f"Webhook set hatası ({attempt}): {e}")
                time.sleep(1.5)
    else:
        log.warning("WEBHOOK_URL tanımsız, webhook set edilmedi!")


if __name__ == "__main__":
    init_memory()
    setup_webhook()
    port = int(os.getenv("PORT", 8080))
    log.info(f"Flask HTTP server 0.0.0.0:{port} üzerinde çalışıyor.")
    app.run(host="0.0.0.0", port=port)
