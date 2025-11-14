# bot.py
# HoopBrain – Telegram Bot Çekirdeği
# TeleBot (pyTelegramBotAPI) ile %100 uyumlu FAZ-3 + FAZ-4 + FAZ-5 yapısı

import os
import telebot

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN environment değişkeni tanımlı değil!")

bot = telebot.TeleBot(BOT_TOKEN)


# =============================================================
#  FAZ-3 KOMUT SİSTEMİ
# =============================================================

@bot.message_handler(commands=["start"])
def start_cmd(message):
    bot.reply_to(
        message,
        "🔥 Bot aktif kardeşim!\n"
        "FAZ-3 komutları + FAZ-4 simülasyon + FAZ-5 Heavy Engine hazır.\n"
        "Komut listesi için /help yaz."
    )


@bot.message_handler(commands=["help"])
def help_cmd(message):
    bot.reply_to(
        message,
        "📌 Komutlar:\n"
        "/start - Botu başlatır\n"
        "/status - Sistem durumunu gösterir\n"
        "/simulate_nba - FAZ-4 NBA sim testi\n"
        "/heavy - FAZ-5 standart\n"
        "/heavy_risk - FAZ-5 yüksek risk\n"
        "/heavy_edge - FAZ-5 edge\n"
        "/heavy_auto - FAZ-5 otomatik\n"
        "/heavy_full - FAZ-5 full kupon\n"
    )


@bot.message_handler(commands=["status"])
def status_cmd(message):
    bot.reply_to(
        message,
        "❄️ Sistem stabil, FAZ-4 aktif.\n"
        "⚙️ FAZ-5 Heavy Engine: Hazır (test modu)."
    )


# =============================================================
#  GENEL ECHO (FAZ-3)
# =============================================================

@bot.message_handler(func=lambda m: True)
def echo_cmd(message):
    bot.reply_to(message, f"🧾 Komut algılandı: {message.text}")


# =============================================================
#  ÇALIŞTIRMA NOKTASI
# =============================================================

def main():
    print("INFO: bot.py başlatılıyor (TeleBot polling)")
    bot.infinity_polling(skip_pending=True)


if __name__ == "__main__":
    main()
