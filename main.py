import sys
import os
from typing import List
from telebot import TeleBot

# ===============================
#  BOT AYARLARI
# ===============================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN ortam değişkeni tanımlı değil.")
    sys.exit(1)

bot = TeleBot(BOT_TOKEN)

# ===============================
#  FAZ-4 NBA SİMÜLASYON MOTORU
# ===============================
from nba_fetcher import fetch_nba_live_games
from nba_analyzer import analyze_live_games
from nba_models import NBAGameState

def _simple_sim_from_game(game: NBAGameState) -> dict:
    hs = game.home_stats
    aw = game.away_stats

    if not hs or not aw:
        return {
            "home": game.home_team,
            "away": game.away_team,
            "score_est": None,
            "pace_est": None,
            "pick": "YOK",
            "confidence": 0.0,
        }

    score_est = hs.pts + aw.pts

    home_pace = hs.pace_est if hs.pace_est is not None else 0
    away_pace = aw.pace_est if aw.pace_est is not None else 0
    pace_est = round((home_pace + away_pace) / 2, 1)

    diff = hs.pts - aw.pts
    if diff > 0:
        pick = game.home_team
    elif diff < 0:
        pick = game.away_team
    else:
        pick = "DENGELİ"

    from math import fabs
    confidence = max(0.5, min(0.99, fabs(diff) / 20.0))

    return {
        "home": game.home_team,
        "away": game.away_team,
        "score_est": round(score_est, 1),
        "pace_est": pace_est,
        "pick": pick,
        "confidence": round(confidence, 2),
    }

# ===============================
#  FAZ-3 TELEGRAM KOMUT SİSTEMİ
# ===============================

@bot.message_handler(commands=["start"])
def start_cmd(message):
    bot.reply_to(
        message,
        "🔥 Bot aktif!\n"
        "FAZ-3 + FAZ-4 + FAZ-5 + FAZ-6 hazır durumda.\n"
        "Komut listesi için /help yaz."
    )

@bot.message_handler(commands=["help"])
def help_cmd(message):
    bot.reply_to(
        message,
        """
📌 Komutlar:

/start - Botu başlatır
/status - Sistemi gösterir
/simulate_nba - NBA canlı simülasyon

/heavy - FAZ-5 Standart
/heavy_risk - FAZ-5 Risk
/heavy_edge - FAZ-5 Edge
/heavy_auto - FAZ-5 Otomatik
/heavy_full - FAZ-5 Full

/faz6_test - FAZ-6 Test
/faz6_auto - FAZ-6 Auto
/faz6_risk - FAZ-6 Risk
/faz6_edge - FAZ-6 Edge
/faz6_real - FAZ-6 Real
/faz6_balance - FAZ-6 Balance
"""
    )

@bot.message_handler(commands=["status"])
def status_cmd(message):
    bot.reply_to(
        message,
        "🟢 Sistem stabil.\n"
        "FAZ-4 aktif.\nFAZ-5 hazır.\nFAZ-6 tam bağlı."
    )

# ===============================
#  FAZ-4 NBA SİMÜLASYON
# ===============================

@bot.message_handler(commands=["simulate_nba"])
def simulate_nba_cmd(message):
    bot.send_message(message.chat.id, "🏀 Simülasyon başlatılıyor...")

    games: List[NBAGameState] = fetch_nba_live_games()
    if not games:
        bot.send_message(message.chat.id, "Canlı maç verisi bulunamadı.")
        return

    simulation_results = []
    for g in games:
        simulation_results.append(_simple_sim_from_game(g))

    analysis_text = analyze_live_games(games)

    reply = "📊 *FAZ-4 NBA Simülasyon Sonuçları*\n\n"
    for r in simulation_results:
        reply += f"🏠 {r['home']} vs 🛫 {r['away']}\n"
        reply += f"📈 Tahmini Skor: {r['score_est']}\n"
        reply += f"⏱ Tempo: {r['pace_est']}\n"
        reply += f"🎯 Kazanan: {r['pick']} ({int(r['confidence']*100)}%)\n\n"

    reply += "🧠 Ham Analiz:\n" + analysis_text

    bot.send_message(message.chat.id, reply, parse_mode="Markdown")

# ===============================
#  FAZ-5 HEAVY ENGINE
# ===============================

from faz5_engine.heavy_engine_main import run_heavy_engine

@bot.message_handler(commands=["heavy"])
def heavy_cmd(message):
    bot.reply_to(message, run_heavy_engine(mode="standard"))

@bot.message_handler(commands=["heavy_risk"])
def heavy_risk_cmd(message):
    bot.reply_to(message, run_heavy_engine(mode="risk"))

@bot.message_handler(commands=["heavy_edge"])
def heavy_edge_cmd(message):
    bot.reply_to(message, run_heavy_engine(mode="edge"))

@bot.message_handler(commands=["heavy_auto"])
def heavy_auto_cmd(message):
    bot.reply_to(message, run_heavy_engine(mode="auto"))

@bot.message_handler(commands=["heavy_full"])
def heavy_full_cmd(message):
    bot.reply_to(message, run_heavy_engine(mode="full"))

# ===============================
#  FAZ-6 ENGINE KOMUTLARI
# ===============================

from faz6_engine.faz6_engine_main import run_faz6_engine

@bot.message_handler(commands=["faz6_test"])
def faz6_test_cmd(message):
    try:
        result = run_faz6_engine(mode="test")
        bot.reply_to(
            message,
            f"🧪 FAZ-6 TEST SONUCU:\n\n{result}"
        )
    except Exception as e:
        bot.reply_to(
            message,
            f"❌ FAZ-6 TEST HATASI:\n\n{e}"
        )

@bot.message_handler(commands=["faz6_auto"])
def faz6_auto_cmd(message):
    bot.reply_to(message, run_faz6_engine(mode="auto"))

@bot.message_handler(commands=["faz6_risk"])
def faz6_risk_cmd(message):
    bot.reply_to(message, run_faz6_engine(mode="risk"))

@bot.message_handler(commands=["faz6_edge"])
def faz6_edge_cmd(message):
    bot.reply_to(message, run_faz6_engine(mode="edge"))

@bot.message_handler(commands=["faz6_real"])
def faz6_real_cmd(message):
    bot.reply_to(message, run_faz6_engine(mode="real"))

@bot.message_handler(commands=["faz6_balance"])
def faz6_balance_cmd(message):
    bot.reply_to(message, run_faz6_engine(mode="balance"))

# ===============================
#  ÇALIŞTIRMA NOKTASI
# ===============================

def main():
    print("INFO: Tüm motorlar aktif.")
    bot.infinity_polling(skip_pending=True)

if __name__ == "__main__":
    main() 
