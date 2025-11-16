import sys
import os
import logging
from typing import List
from telebot import TeleBot

# ===============================
#  LOG AYARLARI
# ===============================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("zeynal_bot_core")

# ===============================
#  BOT AYARLARI
# ===============================

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("BOT_TOKEN ortam değişkeni tanımlı değil. Çıkılıyor.")
    print("ERROR: BOT_TOKEN ortam değişkeni tanımlı değil.")
    sys.exit(1)

bot = TeleBot(BOT_TOKEN)
logger.info("TeleBot örneği oluşturuldu.")

# ===============================
#  FAZ-4 NBA SİMÜLASYON MOTORU
# ===============================

from nba_fetcher import fetch_nba_live_games
from nba_analyzer import analyze_live_games
from nba_models import NBAGameState


def _simple_sim_from_game(game: NBAGameState) -> dict:
    """
    FAZ-4 basit simülasyon çekirdeği.
    Burada kasıtlı olarak model sade tutuluyor; FAZ-5 / FAZ-6 tarafı
    heavy engine ile daha karmaşık hale gelecek.
    """
    hs = game.home_stats
    aw = game.away_stats

    if not hs or not aw:
        logger.warning(
            "Eksik istatistik verisi nedeniyle basit sim yapılmadı: %s vs %s",
            game.home_team,
            game.away_team,
        )
        return {
            "home": game.home_team,
            "away": game.away_team,
            "score_est": None,
            "pace_est": None,
            "pick": "YOK",
            "confidence": 0.0,
        }

    # Toplam skor tahmini (çok basit, FAZ-4)
    score_est = hs.pts + aw.pts

    # Pace tahmini
    home_pace = hs.pace_est if getattr(hs, "pace_est", None) is not None else 0
    away_pace = aw.pace_est if getattr(aw, "pace_est", None) is not None else 0
    pace_est = round((home_pace + away_pace) / 2, 1) if (home_pace or away_pace) else 0.0

    # Fark ve kazanan tahmini
    diff = hs.pts - aw.pts
    if diff > 0:
        pick = game.home_team
    elif diff < 0:
        pick = game.away_team
    else:
        pick = "DENGELİ"

    from math import fabs

    # Güven skoru (çok kaba FAZ-4 modeli; 0.50 - 0.99 aralığına sıkıştırılmış)
    raw_conf = fabs(diff) / 20.0
    confidence = max(0.5, min(0.99, raw_conf))

    result = {
        "home": game.home_team,
        "away": game.away_team,
        "score_est": round(score_est, 1),
        "pace_est": pace_est,
        "pick": pick,
        "confidence": round(confidence, 2),
    }

    logger.debug(
        "Basit sim sonucu | %s vs %s | pick=%s | conf=%.2f",
        result["home"],
        result["away"],
        result["pick"],
        result["confidence"],
    )

    return result


# ===============================
#  FAZ-3 TELEGRAM KOMUT SİSTEMİ
# ===============================


@bot.message_handler(commands=["start"])
def start_cmd(message):
    try:
        logger.info("Kullanıcı /start komutunu çalıştırdı. chat_id=%s", message.chat.id)
        bot.reply_to(
            message,
            "🔥 Bot aktif!\n"
            "FAZ-3 + FAZ-4 + FAZ-5 + FAZ-6 hazır durumda.\n"
            "Komut listesi için /help yaz."
        )
    except Exception as e:
        logger.exception("start_cmd sırasında hata: %s", e)
        bot.reply_to(message, "❌ /start sırasında beklenmeyen bir hata oluştu.")


@bot.message_handler(commands=["help"])
def help_cmd(message):
    try:
        logger.info("Kullanıcı /help komutunu çalıştırdı. chat_id=%s", message.chat.id)
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
    except Exception as e:
        logger.exception("help_cmd sırasında hata: %s", e)
        bot.reply_to(message, "❌ /help sırasında beklenmeyen bir hata oluştu.")


@bot.message_handler(commands=["status"])
def status_cmd(message):
    try:
        logger.info("Kullanıcı /status komutunu çalıştırdı. chat_id=%s", message.chat.id)
        # Buraya ileride FAZ-4 / FAZ-5 / FAZ-6 health-check sonuçları eklenebilir.
        bot.reply_to(
            message,
            "🟢 Sistem stabil.\n"
            "FAZ-4 aktif.\nFAZ-5 hazır.\nFAZ-6 tam bağlı."
        )
    except Exception as e:
        logger.exception("status_cmd sırasında hata: %s", e)
        bot.reply_to(message, "❌ /status sırasında beklenmeyen bir hata oluştu.")


# ===============================
#  FAZ-4 NBA SİMÜLASYON
# ===============================


@bot.message_handler(commands=["simulate_nba"])
def simulate_nba_cmd(message):
    logger.info("Kullanıcı /simulate_nba komutunu çalıştırdı. chat_id=%s", message.chat.id)
    bot.send_message(message.chat.id, "🏀 Simülasyon başlatılıyor...")

    try:
        games: List[NBAGameState] = fetch_nba_live_games()
        logger.info("NBA canlı maç sayısı: %d", len(games) if games else 0)

        if not games:
            bot.send_message(message.chat.id, "Canlı maç verisi bulunamadı.")
            return

        simulation_results = []
        for g in games:
            try:
                sim_res = _simple_sim_from_game(g)
                simulation_results.append(sim_res)
            except Exception as e:
                logger.exception(
                    "Tekil maç simülasyonunda hata: %s vs %s | hata=%s",
                    getattr(g, "home_team", "?"),
                    getattr(g, "away_team", "?"),
                    e,
                )

        # FAZ-4 ham analiz
        try:
            analysis_text = analyze_live_games(games)
        except Exception as e:
            logger.exception("analyze_live_games sırasında hata: %s", e)
            analysis_text = "Analiz sırasında hata oluştu, ham FAZ-4 analizi getirilemedi."

        reply = "📊 *FAZ-4 NBA Simülasyon Sonuçları*\n\n"
        for r in simulation_results:
            reply += f"🏠 {r['home']} vs 🛫 {r['away']}\n"
            if r["score_est"] is not None:
                reply += f"📈 Tahmini Skor: {r['score_est']}\n"
            else:
                reply += "📈 Tahmini Skor: YOK (eksik veri)\n"
            reply += f"⏱ Tempo: {r['pace_est']}\n"
            reply += f"🎯 Kazanan: {r['pick']} ({int(r['confidence'] * 100)}%)\n\n"

        reply += "🧠 Ham Analiz:\n" + analysis_text

        bot.send_message(message.chat.id, reply, parse_mode="Markdown")
    except Exception as e:
        logger.exception("simulate_nba_cmd genel hata: %s", e)
        bot.send_message(
            message.chat.id,
            "❌ /simulate_nba sırasında beklenmeyen bir hata oluştu."
        )


# ===============================
#  FAZ-5 HEAVY ENGINE
# ===============================

from faz5_engine.heavy_engine_main import run_heavy_engine


def _run_heavy_safe(message, mode: str):
    logger.info("FAZ-5 heavy_engine çağrısı: mode=%s | chat_id=%s", mode, message.chat.id)
    try:
        result = run_heavy_engine(mode=mode)
        bot.reply_to(message, result)
    except Exception as e:
        logger.exception("run_heavy_engine(%s) sırasında hata: %s", mode, e)
        bot.reply_to(
            message,
            f"❌ FAZ-5 ({mode}) çalıştırılırken hata oluştu.\n\n{e}"
        )


@bot.message_handler(commands=["heavy"])
def heavy_cmd(message):
    _run_heavy_safe(message, mode="standard")


@bot.message_handler(commands=["heavy_risk"])
def heavy_risk_cmd(message):
    _run_heavy_safe(message, mode="risk")


@bot.message_handler(commands=["heavy_edge"])
def heavy_edge_cmd(message):
    _run_heavy_safe(message, mode="edge")


@bot.message_handler(commands=["heavy_auto"])
def heavy_auto_cmd(message):
    _run_heavy_safe(message, mode="auto")


@bot.message_handler(commands=["heavy_full"])
def heavy_full_cmd(message):
    _run_heavy_safe(message, mode="full")


# ===============================
#  FAZ-6 ENGINE KOMUTLARI
# ===============================

from faz6_engine.faz6_engine_main import run_faz6_engine


def _run_faz6_safe(message, mode: str, label: str):
    logger.info("FAZ-6 engine çağrısı: mode=%s | chat_id=%s", mode, message.chat.id)
    try:
        result = run_faz6_engine(mode=mode)
        prefix = f"{label} SONUCU:" if label else "FAZ-6 SONUCU:"
        bot.reply_to(
            message,
            f"🧠 {prefix}\n\n{result}"
        )
    except Exception as e:
        logger.exception("run_faz6_engine(%s) sırasında hata: %s", mode, e)
        bot.reply_to(
            message,
            f"❌ FAZ-6 ({mode}) sırasında hata oluştu.\n\n{e}"
        )


@bot.message_handler(commands=["faz6_test"])
def faz6_test_cmd(message):
    _run_faz6_safe(message, mode="test", label="FAZ-6 TEST")


@bot.message_handler(commands=["faz6_auto"])
def faz6_auto_cmd(message):
    _run_faz6_safe(message, mode="auto", label="FAZ-6 AUTO")


@bot.message_handler(commands=["faz6_risk"])
def faz6_risk_cmd(message):
    _run_faz6_safe(message, mode="risk", label="FAZ-6 RISK")


@bot.message_handler(commands=["faz6_edge"])
def faz6_edge_cmd(message):
    _run_faz6_safe(message, mode="edge", label="FAZ-6 EDGE")


@bot.message_handler(commands=["faz6_real"])
def faz6_real_cmd(message):
    _run_faz6_safe(message, mode="real", label="FAZ-6 REAL")


@bot.message_handler(commands=["faz6_balance"])
def faz6_balance_cmd(message):
    _run_faz6_safe(message, mode="balance", label="FAZ-6 BALANCE")


# ===============================
#  ÇALIŞTIRMA NOKTASI
# ===============================


def main():
    logger.info("Bot başlatılıyor. Tüm motorlar aktif edilmeye hazırlanıyor...")
    print("INFO: Tüm motorlar aktif. Bot başlatılıyor...")

    try:
        # İleride buraya FAZ-4/5/6 self-check adımları eklenebilir.
        bot.infinity_polling(skip_pending=True)
    except KeyboardInterrupt:
        logger.warning("KeyboardInterrupt alındı, bot durduruluyor...")
        print("Bot manuel olarak durduruldu.")
    except Exception as e:
        logger.exception("Bot ana döngüsünde kritik hata: %s", e)
        print(f"CRITICAL: Bot ana döngüsünde hata oluştu: {e}")


if __name__ == "__main__":
    main() 
