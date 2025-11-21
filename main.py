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
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://zeynal-bot-core.fly.dev/webhook

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

    # slope (SVD fallback)
    try:
        slope = float(np.polyfit(df["t"], df["conf"], 1)[0])
    except:
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
def _faz81_core_calibration(conf, edge, stake):
    brain = faz79_brain()
    mode = brain["mode"]
    trend = brain["trend"]
    vol = brain["vol"]

    conf = float(conf)
    edge = float(edge)
    stake = float(stake)

    if mode not in ("SAFE", "BAL", "AGG"):
        return {
            "engine": "8.1",
            "mode": mode,
            "trend": trend,
            "vol": vol,
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
    else:
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
        "engine": "8.1",
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
    mode = calib["mode"]
    trend = calib["trend"]
    vol = float(calib["vol"])
    conf = float(calib["conf"])
    edge = float(calib["edge"])
    stake = float(calib["stake"])

    profiles = {
        "SAFE":  (0.030, 0.020, 0.08, 0.18, 1.05, 0.88),
        "BAL":   (0.028, 0.018, 0.10, 0.22, 1.04, 0.90),
        "AGG":   (0.025, 0.015, 0.12, 0.26, 1.03, 0.92),
    }

    edge_floor, edge_hard, vsoft, vhard, upf, downf = profiles.get(mode, profiles["BAL"])

    if edge < edge_hard:
        stake *= 0.45
        conf *= 0.80
    elif edge < edge_floor:
        stake *= 0.70
        conf *= 0.90

    if vol > vhard:
        stake *= 0.65
        conf *= 0.90
    elif vol > vsoft:
        stake *= 0.80
        conf *= 0.95

    if trend == "DOWN":
        stake *= downf
        conf *= downf
    elif trend == "UP":
        stake *= upf
        conf *= upf

    conf = max(0.0, min(conf, 0.99))
    stake = max(0.1, stake)

    calib["engine"] = "8.2"
    calib["conf"] = round(conf, 3)
    calib["edge"] = round(edge, 3)
    calib["stake"] = round(stake, 2)
    return calib


# ================================================================
# FAZ-8.3 DYNAMIC BUCKET OPTIMIZER
# ================================================================
def _faz83_dynamic_optimizer(calib):
    conf = float(calib["conf"])
    edge = float(calib["edge"])
    stake = float(calib["stake"])
    vol = float(calib["vol"])

    bucket = 1.0
    if conf > 0.70 and edge > 0.045:
        bucket += 0.10
    if conf > 0.75:
        bucket += 0.05
    if vol < 0.05:
        bucket += 0.05
    if vol > 0.20:
        bucket -= 0.10

    final_stake = max(0.1, stake * bucket)

    calib["engine"] = "8.3"
    calib["stake"] = round(final_stake, 2)
    return calib


# ================================================================
# FAZ-8 PUBLIC CALIBRATION
# ================================================================
def faz8_calibrate_signal(conf, edge, stake=1.0):
    c1 = _faz81_core_calibration(conf, edge, stake)
    if c1["mode"] not in ("SAFE", "BAL", "AGG"):
        c1["engine"] = "8.3"
        return c1
    c2 = _faz82_lmf_shield(c1)
    c3 = _faz83_dynamic_optimizer(c2)
    return c3


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
        "📊 <b>FAZ-7.9 HAFIZA</b>\n\n"
        f"SAFE: {mem['safe']}\n"
        f"BAL: {mem['bal']}\n"
        f"AGG: {mem['agg']}\n\n"
        f"Conf Ort: <b>{df['conf'].mean():.3f}</b>\n"
        f"Edge Ort: <b>{df['edge'].mean():.3f}</b>"
    )
    bot.reply_to(message, msg)

@bot.message_handler(commands=["faz7_plan"])
def cmd_faz7_plan(message):
    info = faz79_brain()
    bot.reply_to(message,
        f"🧠 <b>FAZ-7.9 STRATEJİ</b>\n"
        f"Mod: <b>{info['mode']}</b>\n"
        f"Trend: {info['trend']}\n"
        f"Vol: {info['vol']}\n"
        f"Slope: {info['slope']}\n"
        f"Conf: {info['conf']} | Edge: {info['edge']}"
    )

@bot.message_handler(commands=["faz7_register"])
def cmd_faz7_register(message):
    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(message, "Kullanım: /faz7_register conf edge")
        return
    c = float(parts[1])
    e = float(parts[2])
    register_daily_stats(c, e)
    info = faz79_brain()
    bot.reply_to(message,
        f"Kayıt alındı.\nYeni Mod: {info['mode']} | Trend: {info['trend']}"
    )


# ================================================================
# TELEGRAM KOMUTLARI – FAZ-8.x
# ================================================================
@bot.message_handler(commands=["faz8_status"])
def cmd_faz8_status(message):
    raw_conf = 0.64
    raw_edge = 0.038
    calib = faz8_calibrate_signal(raw_conf, raw_edge, 1.0)

    bot.reply_to(message,
        "🧪 <b>FAZ-8.3 STATUS</b>\n"
        f"Mode: {calib['mode']} | Trend: {calib['trend']}\n"
        f"Vol: {calib['vol']} | Engine: {calib['engine']}\n"
        f"Final → Conf={calib['conf']} Edge={calib['edge']} Stake={calib['stake']}"
    )

@bot.message_handler(commands=["faz8_test"])
def cmd_faz8_test(message):
    parts = message.text.split()
    if len(parts) not in (3,4):
        bot.reply_to(message, "Kullanım: /faz8_test conf edge [stake]")
        return
    conf = float(parts[1])
    edge = float(parts[2])
    stake = float(parts[3]) if len(parts)==4 else 1.0
    calib = faz8_calibrate_signal(conf, edge, stake)

    bot.reply_to(message,
        f"🧪 <b>FAZ-8.3 Test</b>\n"
        f"Mode={calib['mode']} Trend={calib['trend']} Vol={calib['vol']}\n"
        f"Conf={calib['conf']} Edge={calib['edge']} Stake={calib['stake']}"
    )

# MEGA TEST
@bot.message_handler(commands=["faz83_mega"])
def faz83_mega(message):
    tests = [
        (0.55, 0.020, 1.0),
        (0.62, 0.035, 1.0),
        (0.70, 0.050, 1.0),
    ]
    out = "🧪 <b>FAZ-8.3 MEGA TEST</b>\n\n"
    for conf, edge, stk in tests:
        c = faz8_calibrate_signal(conf, edge, stk)
        out += (
            f"Input: conf={conf}, edge={edge}\n"
            f"→ Mode={c['mode']} Trend={c['trend']} Vol={c['vol']}\n"
            f"→ Engine={c['engine']}\n"
            f"→ Final: Conf={c['conf']} Edge={c['edge']} Stake={c['stake']}\n\n"
        )
    bot.reply_to(message, out)


# ================================================================
# STARTUP
# ================================================================
def setup_webhook():
    try:
        bot.delete_webhook()
    except:
        pass

    if WEBHOOK_URL:
        for i in range(1,4):
            try:
                log.info(f"Webhook deneme {i}: {WEBHOOK_URL}")
                bot.set_webhook(url=WEBHOOK_URL)
                log.info("Webhook OK")
                break
            except Exception as e:
                log.error(f"Webhook hata {i}: {e}")
                time.sleep(1.5)

if __name__ == "__main__":
    init_memory()
    setup_webhook()
    port = int(os.getenv("PORT", 8080))
    log.info(f"Server 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port)
