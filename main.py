# main.py
# FAZ 3 – Telegram komut senkronizasyonu (sadeleştirilmiş test sürümü)

import telebot
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.reply_to(message, "🔥 Bot aktif kardeşim. Devam ediyoruz!")

@bot.message_handler(commands=['status'])
def status_cmd(message):
    bot.reply_to(message, "⚙️ Sistem stabil. FAZ-3 aktif, polling çalışıyor, makineler senkron.")

@bot.message_handler(commands=['help'])
def help_cmd(message):
    bot.reply_to(message,
    "📘 Komutlar:\n"
    "/start - Botu başlatır\n"
    "/status - Sistem durumunu gösterir\n"
    "/analyze <lig> - Belirtilen ligi analiz eder (ör: /analyze nba)")

@bot.message_handler(commands=['analyze'])
def analyze_cmd(message):
    try:
        league = message.text.split(' ')[1].upper()
    except IndexError:
        league = "GENEL"
    bot.reply_to(message, f"📊 {league} ligi analizi başlatılıyor (test modu).")

# DEBUG: Her mesajı yakalayıp ne geldiğini loglayan test
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.reply_to(message, f"📡 Komut algılandı: {message.text}")

def main():
    print("INFO: Zeynal Core FAZ-3 başlatılıyor...")
    bot.polling(none_stop=True, skip_pending=True, interval=1)

if __name__ == "__main__":
    main()
