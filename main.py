import os
import json
import time
import logging

import numpy as np
import pandas as pd
from flask import Flask, request

import telebot
from telebot import types

# ================================================================
# 🔧 LOGGING
# ================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# ================================================================
# 🔧 CONFIG
# ================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env değişkeni tanımlı değil!")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown", threaded=False)

# Webhook URL:
# 1) fly.io panelde direkt WEBHOOK_URL verilebilir
#    Örn: https://zeynal-bot-core.fly.dev/webhook
# 2) Eğer verilmemişse FLY_APP_NAME'den auto üretmeye çalışır
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
if not WEBHOOK_URL:
    base = os.getenv("WEBHOOK_BASE_URL", "").strip()
    fly_name = os.getenv("FLY_APP_NAME", "").strip()
    if not base and fly_name:
        base = f"https://{fly_name}.fly.dev"
    if base:
        WEBHOOK_URL = f"{base.rstrip('/')}/webhook"

MEMORY_FILE = "faz7_memory.json"

# ================================================================
# 🌐 FLASK APP (Fly.io HTTP + Telegram Webhook)
# ================================================================
app = Flask(__name__)


@app.get("/")
def healthcheck():
    """
    Fly.io health check endpoint.
    """
    return "OK", 200


@app.post("/webhook")
def telegram_webhook():
    """
    Telegram'dan gelen update'leri işle.
    """
    try:
        json_str = request.get_data().decode("utf-8")
        update = types.Update.de_json(json_str)
        bot.process_new_updates([update])
    except Exception as e:
        logging.exception("Webhook update işlenirken hata: %s", e)
        return "ERROR", 500
    return "OK", 200


def setup_webhook():
    """
    Telegram webhook kaydını yap.
    """
    if not WEBHOOK_URL:
        logging.warning("WEBHOOK_URL tanımlı değil, webhook set edilemedi!")
        return

    logging.info("Eski webhook kaldırılıyor...")
    bot.remove_webhook()

    time.sleep(1.0)

    logging.info("Yeni webhook ayarlanıyor: %s", WEBHOOK_URL)
    bot.set_webhook(
        url=WEBHOOK_URL,
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True,
    )
    logging.info("Webhook set edildi.")


# ================================================================
# 📌 FAZ-7 MEMORY ENGINE
# ================================================================
def init_memory():
    if not os.path.exists(MEMORY_FILE):
        data = {
            "days": [],  # günlük hafıza (son 7 gün)
            "safe": 0,
            "bal": 0,
            "agg": 0,
        }
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)


def load_memory():
    init_memory()
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_memory(data):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def register_daily_stats(conf: float, edge: float):
    """
    FAZ-7.9 günlük kayıt.
    Buraya FAZ-6'nın günlük ortalama Conf/Edge değerlerini de
    otomatik olarak gönderebilirsin (kod seviyesinde çağırarak).
    """
    mem = load_memory()
    today = {
        "ts": int(time.time()),
        "conf": float(conf),
        "edge": float(edge),
    }

    mem["days"].append(today)
    # sadece son 7 günü tut
    if len(mem["days"]) > 7:
        mem["days"] = mem["days"][-7:]

    save_memory(mem)


# ================================================================
# 🧠 FAZ-7.9 STRATEJİ BEYNİ
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
            "stake_norm": 1.0,
            "safe": False,
            "bal": True,
            "agg": False,
        }

    df = pd.DataFrame(days)
    df["t"] = range(len(df))

    avg_conf = float(df["conf"].mean())
    avg_edge = float(df["edge"].mean())

    # basit linear regression: conf ~ t
    slope = float(np.polyfit(df["t"], df["conf"], 1)[0])

    if slope > 0.01:
        trend = "UP"
    elif slope < -0.01:
        trend = "DOWN"
    else:
        trend = "FLAT"

    vol = float(df["conf"].std() if len(df) > 1 else 0.0)

    # Mode seçimi
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
        "stake_norm": 1.0,
        "safe": mode == "SAFE",
        "bal": mode == "BAL",
        "agg": mode == "AGG",
    }


# ================================================================
# 📌 KOMUTLAR — GENEL
# ================================================================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    text = (
        "🔥 Bot aktif!\n"
        "FAZ-4 + FAZ-5 + FAZ-6 + FAZ-7.9 bağlı.\n"
        "Komut listesi için /help yaz.\n"
    )
    bot.reply_to(message, text)


@bot.message_handler(commands=["help"])
def cmd_help(message):
    text = (
        "📌 Komutlar:\n\n"
        "/start - Botu başlatır\n"
        "/help - Komut listesi\n"
        "/status - Sistem durumu\n\n"
        "/simulate_nba - NBA canlı simülasyon\n\n"
        "/faz6_test   - FAZ-6 Test\n"
        "/faz6_auto   - FAZ-6 Auto\n"
        "/faz6_risk   - FAZ-6 Risk\n"
        "/faz6_edge   - FAZ-6 Edge\n"
        "/faz6_real   - FAZ-6 Real\n"
        "/faz6_balance - FAZ-6 Balance\n"
        "/faz6_coupon - FAZ-6 Kupon\n\n"
        "/faz7_status   - FAZ-7.9 hafıza özeti\n"
        "/faz7_plan     - FAZ-7.9 strateji planı\n"
        "/faz7_register - FAZ-7.9 günlük kayıt (conf edge)\n"
        "                 Örn: /faz7_register 0.622 0.035\n"
    )
    bot.reply_to(message, text)


@bot.message_handler(commands=["status"])
def cmd_status(message):
    info = faz79_brain()
    text = (
        "🟢 Sistem stabil.\n"
        "FAZ-4 aktif.\n"
        "FAZ-5 bağlı.\n"
        "FAZ-6 tam online.\n"
        "FAZ-7.9 strateji beyni ve hafıza sistemi çalışıyor.\n\n"
        f"Mod: {info['mode']} | Conf: {info['conf']} | Edge: {info['edge']}"
    )
    bot.reply_to(message, text)


# ================================================================
# 📌 FAZ-7.9 KOMUTLARI
# ================================================================
@bot.message_handler(commands=["faz7_status"])
def cmd_faz7_status(message):
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

    bot.reply_to(message, msg)


@bot.message_handler(commands=["faz7_plan"])
def cmd_faz7_plan(message):
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

    bot.reply_to(message, msg)


@bot.message_handler(commands=["faz7_register"])
def cmd_faz7_register(message):
    """
    Manuel günlük kayıt:
      /faz7_register 0.622 0.035
    """
    try:
        parts = message.text.split()
        if len(parts) != 3:
            raise ValueError("Parametre sayısı yanlış")

        conf = float(parts[1].replace(",", "."))
        edge = float(parts[2].replace(",", "."))
        register_daily_stats(conf, edge)

        bot.reply_to(
            message,
            f"✅ FAZ-7.9 günlük kayıt alındı.\nConf: {conf:.3f} | Edge: {edge:.3f}",
        )
    except Exception:
        bot.reply_to(
            message,
            "❌ Kullanım: `/faz7_register 0.622 0.035`",
        )


# ================================================================
# 🏀 FAZ-6 / NBA SİMÜLASYON KOMUTLARI
# ================================================================
# Buradaki handler'ların yerini, senin mevcut projendeki
# gerçek FAZ-5 / FAZ-6 / simulate_nba fonksiyonlarıyla
# birebir değiştirebilirsin. Placeholder olarak bırakıyorum.

@bot.message_handler(commands=["simulate_nba"])
def cmd_simulate_nba(message):
    bot.reply_to(
        message,
        "🏀 Simülasyon başlatılıyor...\n\n"
        "Bu placeholder. Kendi simulate_nba motorunu burada çağır."
    )


@bot.message_handler(commands=["faz6_coupon"])
def cmd_faz6_coupon(message):
    bot.reply_to(
        message,
        "🔥 FAZ-6 kupon motoru aktif.\n"
        "Bu placeholder. Mevcut FAZ-6 kupon fonksiyonunu buraya bağlayabilirsin."
    )

# Buraya istersen:
# - /heavy, /heavy_auto, /faz6_test, /faz6_edge, /faz6_balance ...
# gibi kendi handler'larını ekleyebilirsin.


# ================================================================
# 🚀 MAIN
# ================================================================
if __name__ == "__main__":
    logging.info("FAZ-7.9 + Flask + Webhook modunda başlıyor...")
    init_memory()

    setup_webhook()

    port = int(os.getenv("PORT", "8080"))
    logging.info("Flask HTTP server 0.0.0.0:%d üzerinde çalışıyor.", port)
    app.run(host="0.0.0.0", port=port)
