# main.py
# HoopBrain Core
# FAZ-3 Komut Sistemi + FAZ-4 NBA Simülasyon Testi

import os
import telebot

from typing import List, Optional
from nba_fetcher import fetch_nba_live_games
from nba_analyzer import analyze_live_games
from nba_models import NBAGameState, NBATeamStatsLite

# -------------------------------------------------------------
# BOT AYARLARI
# -------------------------------------------------------------

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

# -------------------------------------------------------------
# FAZ-4: NBA SİMÜLASYON TEST KOMUTU
# -------------------------------------------------------------

def _simple_sim_from_game(game: NBAGameState) -> dict:
    """
    NBAGameState için basit simülasyon:
    - Mevcut dummy istatistiklerden tahmini toplam skor ve tempo çıkarır.
    - Kimin daha güçlü göründüğüne göre pick yapar.
    """
    hs: Optional[NBATeamStatsLite] = game.home_stats
    aw: Optional[NBATeamStatsLite] = game.away_stats

    if not hs or not aw:
        return {
            "home": game.home_team,
            "away": game.away_team,
            "score_est": None,
            "pace_est": None,
            "pick": "VERİ YOK",
            "confidence": 0.0,
        }

    # Tahmini toplam skor
    score_est = hs.pts + aw.pts

    # Pace tahmini – varsa pace_est kullan, yoksa 100 kabul et
    home_pace = hs.pace_est if hs.pace_est is not None else 100.0
    away_pace = aw.pace_est if aw.pace_est is not None else 100.0
    pace_est = round((home_pace + away_pace) / 2, 1)

    # Basit güç farkı
    diff = hs.pts - aw.pts
    if diff > 0:
        pick = game.home_team
    elif diff < 0:
        pick = game.away_team
    else:
        pick = "DENGELİ"

    # Güven skoru (dummy)
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
def simulate_nba(message):
    """
    FAZ-4 NBA Simülasyon Test Komutu
    """
    try:
        bot.send_message(message.chat.id, "⏳ Simülasyon başlatılıyor...")

        # 1) Canlı (dummy) NBA maçlarını çek
        games: List[NBAGameState] = fetch_nba_live_games()

        if not games:
            bot.send_message(
                message.chat.id,
                "Simülasyon için canlı maç datası bulunamadı."
            )
            return

        # 2) Her maç için basit simülasyon
        simulation_results: List[dict] = []
        for g in games:
            sim = _simple_sim_from_game(g)
            simulation_results.append(sim)

        # 3) Metinsel analiz (mevcut analyzer'ı kullan)
        analysis_text = analyze_live_games(games)

        # 4) Çıktıyı formatla
        reply = "🔮 *FAZ-4 NBA Simülasyon Sonuçları*\n\n"
        for r in simulation_results:
            reply += f"🏀 {r['home']} vs {r['away']}\n"
            reply += f"🎯 Tahmini Toplam Skor: {r['score_est']}\n"
            reply += f"🏃 Tempo Tahmini (pace): {r['pace_est']}\n"
            reply += f"✅ Tahmini Kazanan: *{r['pick']}*\n"
            reply += f"🛡 Güven: {int(r['confidence'] * 100)}%\n"
            reply += "──────────────\n"

        reply += "\n📊 *Ham Maç Analizi:*\n"
        reply += analysis_text

        bot.send_message(
            message.chat.id,
            reply,
            parse_mode="Markdown"
        )

    except Exception as e:
        bot.send_message(
            message.chat.id,
            f"❌ Simülasyon Hatası: {str(e)}"
        )


# -------------------------------------------------------------
# FAZ-3: TELEGRAM KOMUT SİSTEMİ
# -------------------------------------------------------------

@bot.message_handler(commands=["start"])
def start_cmd(message):
    bot.reply_to(message, "🔥 Bot aktif kardeşim. Devam ediyoruz!")


@bot.message_handler(commands=["status"])
def status_cmd(message):
    bot.reply_to(
        message,
        "🧊 Sistem stabil. FAZ-4 aktif durumda. (Crove v1.0 - Stabil Çekirdek)"
    )


@bot.message_handler(commands=["help"])
def help_cmd(message):
    bot.reply_to(
        message,
        "📘 Komutlar:\n"
        "/start - Botu başlatır\n"
        "/status - Sistem durumunu gösterir\n"
        "/analyze <liga> - Belirtilen lig için analiz yapar\n"
        "/simulate_nba - FAZ-4 NBA simülasyon testini çalıştırır\n"
    )


@bot.message_handler(commands=["analyze"])
def analyze_cmd(message):
    try:
        league = message.text.split(" ")[1].upper()
    except Exception:
        league = "GENEL"

    bot.reply_to(message, f"📊 {league} Ligi analizi başlatıldı!")


@bot.message_handler(func=lambda m: True)
def echo_all(message):
    bot.reply_to(message, f"📄 Komut algılandı: {message.text}")


# -------------------------------------------------------------
# ÇALIŞTIRMA NOKTASI
# -------------------------------------------------------------

def main():
    print("INFO: Zeynal Core FAZ-3/FAZ-4 (Crove v1.0) başlatılıyor...")
    bot.polling(non_stop=True, skip_pending=True, interval=0)


if __name__ == "__main__":
    main()
