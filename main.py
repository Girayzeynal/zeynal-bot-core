import telebot
import requests
import json
import os
import time
import threading
import numpy as np
import pandas as pd
from flask import Flask

# ================================================================
# 🔧 CONFIG
# ================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

MEMORY_FILE = "faz7_memory.json"


# ================================================================
# 📌 HEALTH CHECK (Fly.io için mini http server)
# ================================================================
app = Flask(__name__)

@app.route("/")
def home():
    return "OK", 200


# ================================================================
# 📌 FAZ-7 Memory Engine
# ================================================================
def init_memory():
    if not os.path.exists(MEMORY_FILE):
        data = {
            "days": [],
            "safe": 0,
            "bal": 0,
            "agg": 0
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


# ================================================================
# 📌 FAZ-7 Günlük Kayıt
# ================================================================
def register_daily_stats(conf, edge):
    mem = load_memory()
    today = {
        "ts": int(time.time()),
        "conf": conf,
        "edge": edge
    }

    mem["days"].append(today)
    if len(mem["days"]) > 7:
        mem["days"] = mem["days"][-7:]

    save_memory(mem)


# ================================================================
# 📌 FAZ-7.9 STRATEJİ BEYNİ
# ================================================================
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
            "agg": False
        }

    df = pd.DataFrame(days)
    df["t"] = range(len(df))

    avg_conf = df["conf"].mean()
    avg_edge = df["edge"].mean()

    slope = float(np.polyfit(df["t"], df["conf"], 1)[0])

    if slope > 0.01:
        trend = "UP"
    elif slope < -0.01:
        trend = "DOWN"
    else:
        trend = "FLAT"

    vol = float(df["conf"].std()) if len(df) > 1 else 0.0

    if avg_conf > 0.7 and avg_edge > 0.05:
        mode = "SAFE"
    elif avg_conf > 0.4:
        mode = "BAL"
    else:
        mode = "AGG"

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
        "agg": mode == "AGG"
    }


# ================================================================
# 📌 FAZ-7 Commands
# ================================================================
@bot.message_handler(commands=["faz7_status"])
def faz7_status(message):
    mem = load_memory()

    if len(mem["days"]) == 0:
        msg = "📊 FAZ-7.9 Hafıza: Henüz veri yok."
    else:
        df = pd.DataFrame(mem["days"])
        msg = (
            "🧠 *FAZ-7.9 HAFIZA ÖZETİ*\n\n"
            f"SAFE: {mem['safe']}\n"
            f"BAL : {mem['bal']}\n"
            f"AGG : {mem['agg']}\n\n"
            f"7 Günlük Ortalama Confidence: {df['conf'].mean():.3f}\n"
            f"7 Günlük Ortalama Edge: {df['edge'].mean():.3f}"
        )

    bot.reply_to(message, msg, parse_mode="Markdown")


@bot.message_handler(commands=["faz7_plan"])
def faz7_plan(message):
    info = faz79_brain()

    msg = (
        "🧠 *FAZ-7.9 STRATEJİ BEYNİ*\n\n"
        f"Mod: {info['mode']}\n"
        f"🔍 Günlük: conf={info['conf']} edge={info['edge']}\n"
        f"📅 Trend: {info['trend']} (slope {info['slope']})\n"
        f"🌪 Volatilite: {info['vol']}\n"
        f"🔧 Stake Normalize: {info['stake_norm']}\n\n"
        f"SAFE: {'✅' if info['safe'] else '❌'}\n"
        f"BAL: {'✅' if info['bal'] else '❌'}\n"
        f"AGG: {'✅' if info['agg'] else '❌'}\n"
    )

    bot.reply_to(message, msg, parse_mode="Markdown")


# ================================================================
# 📌 FAZ-6 Placeholder
# ================================================================
@bot.message_handler(commands=["faz6_coupon"])
def faz6_coupon(message):
    bot.reply_to(message, "FAZ-6 kupon motoru aktif (placeholder).")


# ================================================================
# 🧵 THREADS: Telebot + Flask paralel çalışma
# ================================================================
def run_bot():
    bot.infinity_polling()

def run_flask():
    app.run(host="0.0.0.0", port=8080)


# ================================================================
# 📌 START
# ================================================================
if __name__ == "__main__":
    init_memory()
    print("Zeynal Core AI: FAZ-7.9 Online...")

    t1 = threading.Thread(target=run_bot)
    t2 = threading.Thread(target=run_flask)

    t1.start()
    t2.start()

    t1.join()
    t2.join()
