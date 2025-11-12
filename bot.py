# bot.py — sağlam sürüm
import os
import time
import logging
import telebot
from telebot import apihelper, util

# ——— LOG AYARLARI ———
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ],
)

# ——— TOKEN ———
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    logging.error("BOT_TOKEN ortam değişkeni TANIMSIZ! Fly.io Secrets → BOT_TOKEN olarak ekleyip yeniden deploy et.")
    raise SystemExit(1)

# ——— BOT ———
bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# Ana handler’ları içeri al ve kaydet
try:
    from core_handlers import register_handlers
    register_handlers(bot)
except Exception as e:
    logging.exception("core_handlers yüklenirken hata: %s", e)

# Basit sağlık kontrolü
@bot.message_handler(commands=["start"])
def start_cmd(message):
    bot.send_message(message.chat.id, "🔥 Bot aktif kardeşim. Devam ediyoruz!")

# ——— ÇALIŞTIRMA DÖNGÜSÜ ———
def run():
    while True:
        try:
            logging.info("Bot polling başlıyor...")
            if hasattr(bot, "infinity_polling"):
                # pyTelegramBotAPI >= 4.x
                bot.infinity_polling(timeout=30, long_polling_timeout=30, allowed_updates=util.update_types)
            else:
                # Eski sürüm uyumluluğu
                bot.polling(non_stop=True, interval=0, timeout=30, allowed_updates=util.update_types)
        except apihelper.ApiTelegramException as e:
            logging.exception("ApiTelegramException: %s", e)
            # 409 = başka bir instance çalışıyor / webhook çatışması
            if "409" in str(e) or "Conflict" in str(e):
                logging.warning("409 Conflict — başka bir instance olabilir. 10 sn bekleyip yeniden deniyorum.")
                time.sleep(10)
            else:
                time.sleep(5)
        except Exception as e:
            logging.exception("Genel hata: %s", e)
            time.sleep(5)

if __name__ == "__main__":
    run()
