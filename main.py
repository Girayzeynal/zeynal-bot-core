# ================================================================
#  HoopBrain Ultra Core — MAIN.PY  (PART 1 / 5)
#  Versiyon: 2025-11-28
#  Amaç: Fly.io + Telegram + FAZ0–17 için tek çekirdek mimari
# ================================================================

import os
import time
import json
import logging
from typing import Any, Dict

import telebot
from flask import Flask, request, jsonify

# ================================================================
# 🔧 LOGGING — GLOBAL
# ================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("hoopbrain-core")

# ================================================================
# 🔧 CONFIG — ENV VARS
# ================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Örn: https://zeynal-bot-core.fly.dev
ENGINEERING_MODE = os.getenv("ENGINEERING_MODE", "ON").upper() == "ON"

# Fly.io genelde PORT veriyor, yoksa 8080'e düş
PORT = int(os.getenv("PORT", "8080"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env değişkeni tanımlı değil. Fly.io secrets kontrol et.")

if not WEBHOOK_URL:
    log.warning(
        "WEBHOOK_URL tanımlı değil. "
        "Production'da /webhook için tam URL tanımlaman gerekiyor."
    )

# ================================================================
# 🤖 TELEGRAM BOT + FLASK APP
# ================================================================
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)

# ================================================================
# 🧠 GLOBAL STATE (FAZ-7/10/11/12/13 vs için placeholder)
# ================================================================
STATE: Dict[str, Any] = {
    "boot_ts": time.time(),
    "last_status_ts": None,
    "faZ_memory_ok": False,
    "faZ_brain_loaded": False,
    "version": "HB-ULTRA-CORE-2025.11.28",
}

# ================================================================
# 🔧 HELPER: BOOL ENV PARSER
# ================================================================
def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


# ================================================================
# 🔧 HELPER: UZUN MESAJ GÖNDERİCİ
# ================================================================
def _send_long_text(message, text: str, chunk_size: int = 3500) -> None:
    """
    Telegram 4096 char sınırı için güvenli bölücü.
    """
    if not text:
        return

    for i in range(0, len(text), chunk_size):
        part = text[i : i + chunk_size]
        bot.reply_to(message, part)


# ================================================================
# 🌐 FLASK ROUTE'LERİ
# ================================================================

@app.route("/", methods=["GET"])
def home():
    """
    Health check + basit JSON status.
    Fly.io load balancer burayı kullanabilir.
    """
    now = time.time()
    uptime = now - STATE["boot_ts"]
    STATE["last_status_ts"] = now

    return jsonify(
        {
            "service": "hoopbrain-ultra-core",
            "version": STATE["version"],
            "uptime_sec": int(uptime),
            "engineering_mode": ENGINEERING_MODE,
        }
    ), 200


@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    """
    Telegram'dan gelen update'leri Flask üzerinden TeleBot'a aktarır.
    Fly.io'da `python main.py` ile çalışacak şekilde tasarlandı.
    """
    try:
        if request.headers.get("content-type") == "application/json":
            json_str = request.get_data().decode("utf-8")
            update = telebot.types.Update.de_json(json_str)
            bot.process_new_updates([update])
        else:
            log.warning("Bilinmeyen content-type alındı: %s", request.headers.get("content-type"))
        return "OK", 200
    except Exception as e:
        log.exception("Webhook işlenirken hata: %s", e)
        return "ERROR", 500


# ================================================================
# 🔧 WEBHOOK REGISTRATION
# ================================================================
def register_webhook():
    """
    Bot açılışında webhook'u temiz şekilde yeniden kurar.
    """
    if not WEBHOOK_URL:
        log.warning("WEBHOOK_URL yok, webhook set edilmedi. (Localse polling düşünebilirsin.)")
        return

    full_url = WEBHOOK_URL.rstrip("/") + "/webhook"

    try:
        log.info("Eski webhook siliniyor...")
        bot.remove_webhook()
        time.sleep(0.5)
        log.info("Yeni webhook ayarlanıyor: %s", full_url)
        bot.set_webhook(url=full_url, drop_pending_updates=True)
        log.info("Webhook başarıyla ayarlandı.")
    except Exception as e:
        log.exception("Webhook ayarlanırken hata: %s", e)


# ================================================================
# 🧪 BASİT /status KOMUTU  (çekirdeğin ayakta olduğunu kanıtlar)
# ================================================================
@bot.message_handler(commands=["status", "start"])
def cmd_status(message):
    """
    En temel canlılık testi.
    Buradan sonra diğer FAZ komutları eklenecek.
    """
    now = time.time()
    uptime_min = (now - STATE["boot_ts"]) / 60.0

    text = (
        "✅ <b>HoopBrain Ultra Core Çalışıyor</b>\n\n"
        f"• Versiyon : <code>{STATE['version']}</code>\n"
        f"• Uptime   : <b>{uptime_min:.1f} dk</b>\n"
        f"• ENGINEERING_MODE : <b>{'ON' if ENGINEERING_MODE else 'OFF'}</b>\n"
        "\n"
        "Burası çekirdek oda. /mac, /mac_img, /live13, FAZ-7/10/11/12/13 "
        "ve kupon motorları bir sonraki parçalarda eklenecek. 🔧"
    )
    bot.reply_to(message, text)


# ================================================================
# 🚀 MAIN ENTRYPOINT
# ================================================================
def main():
    log.info("HoopBrain Ultra Core boot ediyor...")
    register_webhook()
    log.info("Flask server %d portundan dinleyecek.", PORT)
    # debug=False üretimde; threaded=True TeleBot için OK
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
