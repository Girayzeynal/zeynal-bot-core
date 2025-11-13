# main.py
# FAZ 3 – Telegram komut senkronizasyonu

import telebot
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")


@bot.message_handler(commands=["start"])
def start_cmd(message):
    bot.reply_to(message, "🔥 Bot aktif kardeşim. Devam ediyoruz!")


@bot.message_handler(commands=["status"])
def status_cmd(message):
    bot.reply_to(message, "⚙️ Sistem stabil. FAZ-3 aktif durumda.")


@bot.message_handler(commands=["help"])
def help_cmd(message):
    bot.reply_to(
        message,
        "📘 Komutlar:\n"
        "/start - Botu başlatır\n"
        "/status - Sistem durumunu gösterir\n"
        "/analyze <liga> - Belirtilen lig için analiz yapar\n"
    )


@bot.message_handler(commands=["analyze"])
def analyze_cmd(message):
    try:
        league = message.text.split(" ")[1].upper()
    except:
        league = "GENEL"

    bot.reply_to(message, f"📊 {league} ligi analizi başlatıldı!")


@bot.message_handler(func=lambda m: True)
def echo_all(message):
    bot.reply_to(message, f"💬 Komut algılandı: {message.text}")


def main():
    print("INFO: Zeynal Core FAZ-3 başlatılıyor...")
    bot.polling(non_stop=True, skip_pending=True, interval=0)


if __name__ == "__main__":
    main()
