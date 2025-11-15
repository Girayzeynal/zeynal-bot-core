from faz6_engine.faz6_engine_main import run_faz6_engine
from faz5_engine.heavy_engine_main import run_heavy_engine

import sys
import os
from telebot import TeleBot
from typing import List

# ====================================================
# BOT AYARLARI
# ====================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = TeleBot(BOT_TOKEN)

# ====================================================
# FAZ-4 NBA SİMÜLASYON MOTORU
# ====================================================

from nba_fetcher import fetch_nba_live_games
from nba_analyzer import analyze_live_games
from nba_models import NBAGameState, NBATeamStatsLite


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

    from math import fabs
    confidence = max(0.5, min(0.99, fabs(diff) / 20.0 + 0.5))

    return {
        "home": game.home_team,
        "away": game.away_team,
        "score_est": round(score_est, 1),
        "pace_est": pace_est,
        "pick": pick,
        "confidence": round(confidence, 2),
    }


# ====================================================
# FAZ-3 TELEGRAM KOMUT SİSTEMİ
# ====================================================


@bot.message_handler(commands=["start"])
def start_cmd(message):
    bot.reply_to(
        message,
        "🔥 Bot aktif! FAZ-3 + FAZ-4 + FAZ-5 + FAZ-6 hazır.\n"
        "Komut listesi için /help yaz.",
    )


@bot.message_handler(commands=["help"])
def help_cmd(message):
    bot.reply_to(
        message,
        "*Komutlar*\n"
        "/start - Botu başlatır\n"
        "/status - Sistemi gösterir\n"
        "/simulate_nba - NBA simülasyon testi\n"
        "/heavy - FAZ-5 Standart\n"
        "/heavy_risk - FAZ-5 Risk\n"
        "/heavy_edge - FAZ-5 Edge\n"
        "/heavy_auto - FAZ-5 Otomatik\n"
        "/heavy_full - FAZ-5 Full\n"
        "/faz6_test - FAZ-6 test modu\n"
        "/faz6_auto - FAZ-6 auto modu\n"
        "/faz6_risk - FAZ-6 risk modu\n"
        "/faz6_edge - FAZ-6 edge modu\n"
        "/faz6_real - FAZ-6 real modu\n"
        "/faz6_balance - FAZ-6 balance modu\n",
    )


@bot.message_handler(commands=["status"])
def status_cmd(message):
    bot.reply_to(
        message,
        "🟢 Sistem stabil.\n"
        "FAZ-4 aktif.\nFAZ-5 hazır.\nFAZ-6 tam bağlı.",
    )


# ====================================================
# FAZ-4 NBA SİMÜLASYON
# ====================================================


@bot.message_handler(commands=["simulate_nba"])
def simulate_nba_cmd(message):
    bot.send_message(message.chat.id, "🏀 Simülasyon başlatılıyor...")

    games: List[NBAGameState] = fetch_nba_live_games()
    if not games:
        bot.send_message(message.chat.id, "Canlı maç verisi yok.")
        return

    simulation_results = []
    for g in games:
        simulation_results.append(_simple_sim_from_game(g))

    analysis_text = analyze_live_games(games)

    reply = "📊 *FAZ-4 NBA Simülasyon Sonuçları*\n\n"
    for r in simulation_results:
        reply += f"🏠 {r['home']} vs {r['away']}\n"
        reply += f"🎯 Tahmini Skor: {r['score_est']}\n"
        reply += f"⏱ Tempo: {r['pace_est']}\n"
        reply += f"✅ Kazanan: {r['pick']} ({int(r['confidence'] * 100)}%)\n\n"

    reply += "🧠 Ham Analiz:\n" + analysis_text

    bot.send_message(message.chat.id, reply, parse_mode="Markdown")


# ====================================================
# FAZ-5 HEAVY ENGINE
# ====================================================


@bot.message_handler(commands=["heavy"])
def heavy_cmd(message):
    bot.reply_to(
        message, run_heavy_engine(mode="standard"), parse_mode="Markdown"
    )


@bot.message_handler(commands=["heavy_risk"])
def heavy_risk_cmd(message):
    bot.reply_to(
        message, run_heavy_engine(mode="risk"), parse_mode="Markdown"
    )


@bot.message_handler(commands=["heavy_edge"])
def heavy_edge_cmd(message):
    bot.reply_to(
        message, run_heavy_engine(mode="edge"), parse_mode="Markdown"
    )


@bot.message_handler(commands=["heavy_auto"])
def heavy_auto_cmd(message):
    bot.reply_to(
        message, run_heavy_engine(mode="auto"), parse_mode="Markdown"
    )


@bot.message_handler(commands=["heavy_full"])
def heavy_full_cmd(message):
    bot.reply_to(
        message, run_heavy_engine(mode="full"), parse_mode="Markdown"
    )


# ====================================================
# FAZ-6 ENGINE KOMUTLARI
# ====================================================


@bot.message_handler(commands=["faz6_test"])
def faz6_test_cmd(message):
    bot.reply_to(
        message, run_faz6_engine(mode="test"), parse_mode="Markdown"
    )


@bot.message_handler(commands=["faz6_auto"])
def faz6_auto_cmd(message):
    bot.reply_to(
        message, run_faz6_engine(mode="auto"), parse_mode="Markdown"
    )


@bot.message_handler(commands=["faz6_risk"])
def faz6_risk_cmd(message):
    bot.reply_to(
        message, run_faz6_engine(mode="risk"), parse_mode="Markdown"
    )


@bot.message_handler(commands=["faz6_edge"])
def faz6_edge_cmd(message):
    bot.reply_to(
        message, run_faz6_engine(mode="edge"), parse_mode="Markdown"
    )


@bot.message_handler(commands=["faz6_real"])
def faz6_real_cmd(message):
    bot.reply_to(
        message, run_faz6_engine(mode="real"), parse_mode="Markdown"
    )


@bot.message_handler(commands=["faz6_balance"])
def faz6_balance_cmd(message):
    bot.reply_to(
        message, run_faz6_engine(mode="balance"), parse_mode="Markdown"
    )


# ====================================================
# ÇALIŞTIRMA NOKTASI
# ====================================================


def main():
    print("INFO: Tüm motorlar aktif.")
    bot.infinity_polling(skip_pending=True)


if __name__ == "__main__":
    main() 
