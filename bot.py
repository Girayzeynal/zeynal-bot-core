# bot.py (örnek sağlam sürüm)
import os
import time
import logging
import telebot

# LOG ayarları (kayıt dosyası oluşur)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()])

# TOKEN: ya environment değişkeninden al, yoksa uyar
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    logging.error("BOT_TOKEN ortam değişkeni tanımlı değil! export BOT_TOKEN='xxxx' yap.")
    raise SystemExit("BOT_TOKEN tanımlı değil")

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.send_message(message.chat.id, "🔥 Bot aktif kardeşim. Devam ediyoruz!")

# Güvenli sonsuz loop: bağlantı koparsa yeniden bağlan
def run():
    while True:
        try:
            logging.info("Bot polling başlıyor...")
            # non_stop True + timeout makul bir değer
            bot.polling(non_stop=True, interval=0, timeout=30)
        except telebot.apihelper.ApiTelegramException as e:
            logging.error("ApiTelegramException: %s", e)
            # 409 Conflict -> başka bir getUpdates çalışıyor olabilir (başka instance)
            if "409" in str(e):
                logging.error("409 conflict: başka bir bot instance çalışıyor olabilir. Lütfen diğerlerini durdur.")
                # bekleyip yeniden dene, ama uzun bir bekleme koy
                time.sleep(10)
            else:
                time.sleep(3)
        except Exception as e:
            logging.exception("Genel hata: yeniden denenecek")
            time.sleep(3)

if __name__ == "__main__":
    run()
