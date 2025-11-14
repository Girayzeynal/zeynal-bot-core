# main.py
# HoopBrain Core
# FAZ-3 Komut Sistemi + FAZ-4 NBA Simülasyon Testi + FAZ-5 Heavy Engine

import os
from typing import List
import importlib
import subprocess
import sys

import telebot

from nba_fetcher import fetch_nba_live_games
from nba_analyzer import analyze_live_games
from nba_models import NBAGameState, NBATeamStatsLite

# --------------------------------------------------
# BOT AYARLARI
# --------------------------------------------------

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)


# --------------------------------------------------
# FAZ-4: NBA SİMÜLASYON TEST KOMUTU
# --------------------------------------------------

def _simple_sim_from_game(game: NBAGameState) -> dict:
    """
    NBAGameState için basit similasyon:
    - Mevcut dummy istatistiklerden tahmini toplam skor ve tempo çıkarır.
    - Kimin daha güçlü göründüğüne göre pick yapar.
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

    # Tahmini toplam skor (dummy)
    score_est = hs.pts + aw.pts

    # Pace tahmini - varsa pace_est, yoksa 100 kabul et
    home_pace = hs.pace_est if hs.pace_est is not None else 100.0
    away_pace = aw.pace_est if aw.pace_est is not None else 100.0
    pace_est = round((home_pace + away_pace) / 2, 1)

    # Basit güç farkı: skor farkı
    diff = hs.pts - aw.pts
    if diff > 0:
        pick = game.home_team
    elif diff < 0:
        pick = game.away_team
    else:
        pick = "DENGELİ"

    # Güven skoru (tamamen dummy, sadece test için)
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
    """
    FAZ-4 NBA Simülasyon Test Komutu
    """
    try:
        bot.send_message(message.chat.id, "⏳ Simülasyon başlatılıyor...")

        # 1) Canlı (dummy) NBA maçlarını çek
        games: List[NBAGameState] = fetch_nba_live_games()

        if not games:
            bot.send_message(message.chat.id, "Simülasyon için canlı NBA maçı datası bulunamadı.")
            return

        # 2) Her maç için basit similasyon
        simulation_results: list[dict] = []
        for g in games:
            sim = _simple_sim_from_game(g)
            simulation_results.append(sim)

        # 3) Metinsel analiz (mevcut analyzer'ı kullan)
        analysis_text = analyze_live_games(games)

        # 4) Çıktıyı formüle et
        reply = "🔮 *FAZ-4 NBA Simülasyon Sonuçları*\n\n"
        for r in simulation_results:
            reply += f"🏀 {r['home']} vs {r['away']}\n"
            reply += f"🎯 Tahmini Toplam Skor: {r['score_est']}\n"
            reply += f"🏃 Tempo Tahmini (pace): {r['pace_est']}\n"
            reply += f"✅ Tahmini Kazanan: {r['pick']} (güven: {int(r['confidence'] * 100)}%)\n"
            reply += "————————————\n"

        reply += "\n📊 *Ham Maç Analizi:*\n"
        reply += analysis_text

        bot.send_message(message.chat.id, reply, parse_mode="Markdown")

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Simülasyon Hatası: {str(e)}")


# --------------------------------------------------
# FAZ-5: HEAVY ENGINE BAĞLANTISI
# --------------------------------------------------

def run_faz5_engine(mode: str = "full") -> str:
    """
    FAZ-5 Heavy Engine'i çalıştırır ve metin çıktısını döndürür.
    Mod parametresi şimdilik opsiyonel; ileride risk/edge/auto için kullanılabilir.
    """
    try:
        mod = importlib.import_module("faz5_engine.faz5_engine_main")
    except ModuleNotFoundError:
        return "FAZ-5 Heavy Engine modülü (faz5_engine) bulunamadı."

    # 1) Fonksiyon tabanlı dene
    for fname in ("run_heavy_engine", "run", "main"):
        fn = getattr(mod, fname, None)
        if callable(fn):
            try:
                if fn.__code__.co_argcount >= 1:
                    return str(fn(mode))
                else:
                    return str(fn())
            except Exception as e:
                return f"FAZ-5 çalışırken hata oluştu: {e}"

    # 2) Fonksiyon yoksa subprocess ile -m çalıştır
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
        return "FAZ-5 çalıştı ama hiçbir çıktı üretmedi."
    except Exception as e:
        return f"FAZ-5 subprocess hatası: {e}"


@bot.message_handler(commands=["heavy"])
def heavy_cmd(message):
    text = run_faz5_engine(mode="standard")
    bot.reply_to(message, text)


@bot.message_handler(commands=["heavy_risk"])
def heavy_risk_cmd(message):
    text = run_faz5_engine(mode="risk")
    bot.reply_to(message, text)


@bot.message_handler(commands=["heavy_edge"])
def heavy_edge_cmd(message):
    text = run_faz5_engine(mode="edge")
    bot.reply_to(message, text)


@bot.message_handler(commands=["heavy_auto"])
def heavy_auto_cmd(message):
    text = run_faz5_engine(mode="auto")
    bot.reply_to(message, text)


@bot.message_handler(commands=["heavy_full"])
def heavy_full_cmd(message):
    text = run_faz5_engine(mode="full")
    bot.reply_to(message, text)


# --------------------------------------------------
# FAZ-3: TELEGRAM KOMUT SİSTEMİ
# --------------------------------------------------

@bot.message_handler(commands=["start"])
def start_cmd(message):
    bot.reply_to(
        message,
        "🔥 Bot aktif kardeşim. Devam ediyoruz!\n"
        "FAZ-3 komut sistemi + FAZ-4 NBA analizi + FAZ-5 Heavy Engine hazır.\n"
        "Komut listesi için /help yaz."
    )


@bot.message_handler(commands=["status"])
def status_cmd(message):
    bot.reply_to(
        message,
        "❄️ Sistem stabil. FAZ-4 aktif durumda. (Crove v1.0 - Stabil Çekirdek)\n"
        "⚙️ FAZ-5 Heavy Engine: TEST/LOCAL modunda hazır."
    )


@bot.message_handler(commands=["help"])
def help_cmd(message):
    bot.reply_to(
        message,
        "📌 Komutlar:\n"
        "/start - Botu başlatır\n"
        "/status - Sistem durumunu gösterir\n"
        "/analyze nba - NBA ligi analizi\n"
        "/simulate_nba - FAZ-4 NBA simülasyon testi\n"
        "/heavy - FAZ-5 standart kupon\n"
        "/heavy_risk - FAZ-5 yüksek risk kupon\n"
        "/heavy_edge - FAZ-5 edge odaklı kupon\n"
        "/heavy_auto - FAZ-5 otomatik mod\n"
        "/heavy_full - FAZ-5 full paket kupon"
    )


@bot.message_handler(commands=["analyze"])
def analyze_cmd(message):
    try:
        # Örn: "/analyze nba"
        text_parts = message.text.split(" ", 1)
        if len(text_parts) == 1:
            league = "GENEL"
        else:
            league = text_parts[1].upper()

        bot.reply_to(message, f"📊 {league} ligi analizi başlatıldı!")
        # Burada ileride FAZ-3/FAZ-4 genel analiz fonksiyonları bağlanabilir

    except Exception:
        bot.reply_to(message, "❌ Analyze komutunda bir hata oluştu.")


@bot.message_handler(func=lambda m: True)
def echo_all(message):
    bot.reply_to(message, f"🧾 Komut algılandı: {message.text}")


# --------------------------------------------------
# ÇALIŞTIRMA NOKTASI
# --------------------------------------------------

def main():
    print("INFO: Zeynal Core FAZ-3/FAZ-4/FAZ-5 başlatılıyor...")
    bot.infinity_polling(skip_pending=True)


if __name__ == "__main__":
    main()
