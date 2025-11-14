@bot.message_handler(commands=['simulate_nba'])
def simulate_nba(message):
    """
    FAZ-4 NBA Simülasyon Test Komutu
    fetcher → data_pipe → sim_engine → analyzer zincirini test eder.
    """
    try:
        bot.send_message(message.chat.id, "⏳ Simülasyon başlatılıyor…")

        # 1) Dummy canlı maç verisini çek
        from nba_fetcher import fetch_nba_live_games
        live_games = fetch_nba_live_games()

        if not live_games:
            bot.send_message(message.chat.id, "Simülasyon için canlı maç datası bulunamadı.")
            return

        # 2) Veri dönüşümü (data_pipe)
        from data_pipe import transform_game_data
        transformed = transform_game_data(live_games)

        # 3) Simülasyon motoru
        from sim_engine import simulate_game
        simulation_results = []
        for g in transformed:
            result = simulate_game(g)
            simulation_results.append(result)

        # 4) Analiz çıktı formatı
        from nba_analyzer import analyze_live_games
        analysis_text = analyze_live_games(live_games)

        # Sonuç döndür
        reply = "🔥 *FAZ-4 NBA Simülasyon Sonuçları*\n\n"
        for r in simulation_results:
            reply += f"🏀 {r['home']} vs {r['away']}\n"
            reply += f"• Tahmini Toplam Skor: {r['score_est']}\n"
            reply += f"• Pace Tahmini: {r['pace_est']}\n"
            reply += "— — — — — — —\n"

        reply += "\n📊 *Ham Maç Analizi:*\n"
        reply += analysis_text

        bot.send_message(message.chat.id, reply, parse_mode="Markdown")

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Simülasyon Hatası: {str(e)}")# main.py
# FAZ 3 - Telegram komut senkronizasyonu

import telebot
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

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
    bot.reply_to(message, f"🧾 Komut algılandı: {message.text}")

def main():
    print("INFO: Zeynal Core FAZ-3 başlatılıyor...")
    bot.polling(non_stop=True, skip_pending=True, interval=0)

if __name__ == "__main__":
    main()
