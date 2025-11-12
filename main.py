# main.py
# FAZ 3 + Telegram entegrasyonu: veri akışı + simülasyon + komut sistemi

import telebot
from data_pipe import fetch_upcoming_mock
from sim_engine import simulate_game
from utils import log_event, format_game_result
import os

# Telegram token
BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

# /start komutu
@bot.message_handler(commands=['start'])
def start_command(message):
    bot.reply_to(message, "🔥 Bot aktif kardeşim. Devam ediyoruz!")

# /status komutu
@bot.message_handler(commands=['status'])
def status_command(message):
    bot.reply_to(message, "✅ Sistem aktif. Polling çalışıyor, 1 makine bağlı (AMS bölgesi).")

# /help komutu
@bot.message_handler(commands=['help'])
def help_command(message):
    help_text = (
        "🧭 Komutlar:\n"
        "/start - Botu başlat\n"
        "/status - Sistem durumu\n"
        "/analyze [lig] - Simülasyon başlat\n"
        "/help - Bu menüyü göster"
    )
    bot.reply_to(message, help_text)

# /analyze komutu
@bot.message_handler(commands=['analyze'])
def analyze_command(message):
    try:
        query = message.text.split(" ", 1)[1]
        bot.reply_to(message, f"📊 {query.upper()} ligi analizi başlatılıyor...")
        log_event("INFO", f"{query.upper()} ligi analizi tetiklendi.")

        # FAZ 3 çekirdek motoru çalıştır
        games = fetch_upcoming_mock()
        for game in games:
            result = simulate_game(game)
            formatted = format_game_result(game, result)
            bot.send_message(message.chat.id, formatted)

        bot.send_message(message.chat.id, "✅ Tüm simülasyonlar tamamlandı!")
    except IndexError:
        bot.reply_to(message, "⚠️ Lütfen bir lig adı belirt. Örn: /analyze nba")

# Ana döngü
def main():
    log_event("INFO", "Zeynal Core FAZ 3 + Telegram entegrasyonu başlatılıyor...")
    bot.polling(non_stop=True)

if __name__ == "__main__":
    main()
