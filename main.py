# main.py
# FAZ 3 - Komut senkronizasyonu + veri akışı + simülasyon + sonuç gösterimi

import telebot
import os
from data_pipe import fetch_upcoming_mock
from sim_engine import simulate_game
from utils import log_event, format_game_result

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "🔥 Bot aktif kardeşim. Devam ediyoruz!")

@bot.message_handler(commands=['status'])
def send_status(message):
    bot.reply_to(message, "⚙️ Sistem stabil. FAZ-3 aktif, polling çalışıyor, makineler senkron.")

@bot.message_handler(commands=['help'])
def send_help(message):
    bot.reply_to(message, "📘 Komutlar:\n/start - Botu başlatır\n/status - Sistem durumunu gösterir\n/analyze <lig> - Belirtilen ligi simüle eder (ör: /analyze nba)")

@bot.message_handler(commands=['analyze'])
def analyze_league(message):
    try:
        league = message.text.split(' ')[1].upper()
    except IndexError:
        league = "GENEL"

    bot.reply_to(message, f"📊 {league} ligi analizi başlatılıyor...")

    games = fetch_upcoming_mock()
    log_event("INFO", f"{len(games)} maç alındı (mock veri).")

    for game in games:
        result = simulate_game(game)
        formatted = format_game_result(game, result)
        bot.send_message(message.chat.id, f"{league} | {formatted}")

    bot.send_message(message.chat.id, "✅ Analiz tamamlandı. Tüm sonuçlar gönderildi.")

def main():
    log_event("INFO", "Zeynal Core FAZ-3 başlatılıyor...")
    bot.polling(none_stop=True, skip_pending=True, interval=1)

@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.reply_to(message, f"📡 Komut algılandı: {message.text}")
    
if __name__ == "__main__":
    main()
