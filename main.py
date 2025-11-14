# main.py
# HoopBrain Core
# FAZ-3 Komut Sistemi + FAZ-4 NBA Simülasyon Testi + FAZ-5 Heavy Engine Stabil Çekirdek

import os
import sys
import importlib
import subprocess
from typing import List

# Çekirdek PYTHONPATH düzeltmesi (Fly.io → ModuleNotFoundError çözümü)
sys.path.append(os.getcwd())

import telebot

# NBA çekirdek modülleri
from nba_fetcher import fetch_nba_live_games
from nba_analyzer import analyze_live_games
from nba_models import NBAGameState, NBATeamStatsLite


"""
===========================================================
   BOT AYARLARI
===========================================================
"""

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)


"""
===========================================================
   FAZ-4: NBA SİMÜLASYON TESTİ
===========================================================
"""

def _simple_sim_from_game(game: NBAGameState) -> dict:
    """
    NBAGameState için basit similasyon (FAZ-4 test motoru).
    """
    hs: NBATeamStatsLite | None = game.home_stats
    aw: NBATeamStatsLite | None = game.away_stats

    if not hs or not aw:
        return {
            "home": game.home_team,
            "away": game.away_team,
            "score_est": None,
            "pace_est": None,
            "pick": "VERİ YOK",
            "confidence": 0.0,
        }

    score_est = hs.pts + aw.pts

    home_pace = hs.pace_est if hs.pace_est is not None else 100.0
    away_pace = aw.pace_est if aw.pace_est is not None else 100.0
    pace_est = round((home_pace + away_pace) / 2, 1)

    diff = hs.pts - aw.pts
    if diff > 0:
        pick = game.home_team
    elif diff < 0:
        pick = game.away_team
    else:
        pick = "DENGELİ"

    confidence = max(0.5, min(0.99, abs(diff) / 20.0 + 0.5))

    return {
        "home": game.home_team,
        "away": game.away_team,
        "score_est": round(score_est, 1),
        "pace_est": pace_est,
        "pick": pick,
        "confidence": round(confidence, 2),
    }


@bot.message_handler(commands=["simulate_nba"])
def simulate_nba_cmd(message):
    try:
        bot.send_message(message.chat.id, "⏳ Simülasyon başlatılıyor...")

        games: List[NBAGameState] = fetch_nba_live_games()
        if not games:
            bot.send_message(message.chat.id, "Simülasyon için canlı NBA maçı datası bulunamadı.")
            return

        simulation_results = []
        for g in games:
            simulation_results.append(_simple_sim_from_game(g))

        analysis_text = analyze_live_games(games)

        reply = "🔮 *FAZ-4 NBA Simülasyon Sonuçları*\n\n"
        for r in simulation_results:
            reply += f"🏀 {r['home']} vs {r['away']}\n"
            reply += f"🎯 Tahmini Toplam Skor: {r['score_est']}\n"
            reply += f"🏃 Tempo Tahmini: {r['pace_est']}\n"
            reply += f"✅ Tahmini Kazanan: {r['pick']} (%{int(r['confidence'] * 100)})\n"
            reply += "————————————\n"

        reply += "\n📊 *Ham Maç Analizi:*\n" + analysis_text
        bot.send_message(message.chat.id, reply, parse_mode="Markdown")

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Simülasyon Hatası: {str(e)}")



"""
===========================================================
   FAZ-5: HEAVY ENGINE ENTEGRASYONU
===========================================================
"""

def run_faz5_engine(mode: str = "full") -> str:
    """
    FAZ-5 Heavy Engine çağırıcı.
    """

    try:
        mod = importlib.import_module("faz5_engine.faz5_engine_main")
    except ModuleNotFoundError:
        return "FAZ-5 Heavy Engine modülü bulunamadı. (faz5_engine klasörü eksik olabilir)"

    for fname in ("run_heavy_engine", "run", "main"):
        fn = getattr(mod, fname, None)
        if callable(fn):
            try:
                if fn.__code__.co_argcount >= 1:
                    return str(fn(mode))
                else:
                    return str(fn())
            except Exception as e:
                return f"FAZ-5 çalışırken hata: {e}"

    try:
        result = subprocess.run(
            [sys.executable, "-m", "faz5_engine.faz5_engine_main"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.stdout.strip():
            return result.stdout
        if result.stderr.strip():
            return "FAZ-5 hata çıktısı:\n" + result.stderr
        return "FAZ-5 çalıştı fakat çıktı üretmedi."

    except Exception as e:
        return f"FAZ-5 subprocess hatası: {e}"


# FAZ-5 ağır motor komutları
@bot.message_handler(commands=["heavy"])
def heavy_cmd(message):
    bot.reply_to(message, run_faz5_engine("standard"))

@bot.message_handler(commands=["heavy_risk"])
def heavy_risk_cmd(message):
    bot.reply_to(message, run_faz5_engine("risk"))

@bot.message_handler(commands=["heavy_edge"])
def heavy_edge_cmd(message):
    bot.reply_to(message, run_faz5_engine("edge"))

@bot.message_handler(commands=["heavy_auto"])
def heavy_auto_cmd(message):
    bot.reply_to(message, run_faz5_engine("auto"))

@bot.message_handler(commands=["heavy_full"])
def heavy_full_cmd(message):
    bot.reply_to(message, run_faz5_engine("full"))


"""
===========================================================
   FAZ-3: TELEGRAM KOMUT SİSTEMİ
===========================================================
"""

@bot.message_handler(commands=["start"])
def start_cmd(message):
    bot.reply_to(message,
        "🔥 Bot aktif kardeşim!\n"
        "FAZ-3 komutları + FAZ-4 NBA testi + FAZ-5 Heavy Engine hazır.\n"
        "Komut listesi için /help yaz.")

@bot.message_handler(commands=["status"])
def status_cmd(message):
    bot.reply_to(message,
        "❄️ Sistem stabil. FAZ-4 çekirdeği çalışıyor.\n"
        "⚙️ FAZ-5 Heavy Engine: hazır, test modunda.")

@bot.message_handler(commands=["help"])
def help_cmd(message):
    bot.reply_to(message,
        "📌 Komutlar:\n"
        "/start - Botu başlatır\n"
        "/status - Sistem durumunu gösterir\n"
        "/simulate_nba - NBA simülasyon testi\n"
        "/analyze nba - NBA analizi\n"
        "/heavy - FAZ-5 standart kupon\n"
        "/heavy_risk - Yüksek risk kupon\n"
        "/heavy_edge - Edge odaklı kupon\n"
        "/heavy_auto - Otomatik kupon\n"
        "/heavy_full - Full paket kupon\n"
    )

@bot.message_handler(commands=["analyze"])
def analyze_cmd(message):
    try:
        parts = message.text.split(" ", 1)
        league = "GENEL" if len(parts) == 1 else parts[1].upper()
        bot.reply_to(message, f"📊 {league} ligi analizi başlatıldı!")
    except:
        bot.reply_to(message, "❌ Analyze komutunda hata oluştu.")


@bot.message_handler(func=lambda m: True)
def echo_all(message):
    bot.reply_to(message, f"🧾 Komut algılandı: {message.text}")


"""
===========================================================
   ÇALIŞTIRMA NOKTASI
===========================================================
"""

def main():
    print("INFO: FAZ-3/FAZ-4/FAZ-5 çekirdek başlatılıyor...")
    bot.infinity_polling(skip_pending=True)

if __name__ == "__main__":
    main()
