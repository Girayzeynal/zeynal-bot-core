import logging
import threading
from flask import Flask
from telebot import TeleBot, types

# ---------------------------------------------------------
# TELEGRAM BOT TOKEN
# ---------------------------------------------------------
import os
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable missing!")

bot = TeleBot(BOT_TOKEN, parse_mode="HTML")

# ---------------------------------------------------------
# FLY.IO HEALTHCHECK HTTP SERVER
# ---------------------------------------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "OK", 200

# Health check endpoint
@app.route("/health")
def health():
    return "PASS", 200

# ---------------------------------------------------------
# FAZ-6 ENGINE IMPORT (temiz, circular-free)
# ---------------------------------------------------------
try:
    from faz6_engine import run_faz6_engine
except Exception as e:
    logging.error(f"FAZ6 import error: {e}")
    run_faz6_engine = None

# ---------------------------------------------------------
# BOT KOMUTLARI
# ---------------------------------------------------------

@bot.message_handler(commands=["start"])
def start_cmd(message):
    text = (
        "🔥 Bot aktif!\n"
        "FAZ-3 + FAZ-4 + FAZ-5 + FAZ-6 bağlı.\n"
        "Komut listesi için /help yaz."
    )
    bot.reply_to(message, text)

@bot.message_handler(commands=["help"])
def help_cmd(message):
    text = (
        "📌 Komutlar:\n"
        "/start – Botu başlat\n"
        "/help – Komut listesi\n"
        "/cupon – FAZ-6 kupon üret\n"
    )
    bot.reply_to(message, text)

@bot.message_handler(commands=["cupon"])
def cupon_cmd(message):
    try:
        if run_faz6_engine is None:
            bot.reply_to(message, "❌ FAZ-6 çalıştırılamıyor.")
            return

        result = run_faz6_engine()

        reply = (
            "🔥 FAZ-6 Kupon Çıktısı\n"
            f"{result}"
        )
        bot.reply_to(message, reply)

    except Exception as e:
        bot.reply_to(message, f"❌ Kupon oluşturulamadı.\nHata: {e}")

# ---------------------------------------------------------
# THREAD KORUMALI BAŞLATMA
# ---------------------------------------------------------

def start_telegram():
    """Telegram polling ayrı thread’de çalışır; Fly.io restart edemez."""
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=30)
        except Exception as e:
            logging.error(f"Polling error: {e}")
            continue

def start_http():
    """HTTP server healthcheck için zorunlu."""
    app.run(host="0.0.0.0", port=8080, debug=False, use_reloader=False)

# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Telegram thread
    t1 = threading.Thread(target=start_telegram, daemon=True)
    t1.start()

    # HTTP healthcheck thread
    t2 = threading.Thread(target=start_http, daemon=True)
    t2.start()

    # Ana thread sonsuza kadar bekler
    t1.join()
    t2.join()
