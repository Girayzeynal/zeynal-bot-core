import sys
import os
import time
from typing import List
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests
from telebot import TeleBot

# ============================================================
#                     BOT AYARLARI
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN ortam değişkeni tanımlı değil.")
    sys.exit(1)

bot = TeleBot(BOT_TOKEN)


# ============================================================
#            FAZ-4 NBA SİMÜLASYON MOTORU
# ============================================================

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
    pick = game.home_team if diff > 0 else (game.away_team if diff < 0 else "DENGELİ")

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


# ============================================================
#             FAZ-6 TELEGRAM ÇIKTI FORMATLAYICI
# ============================================================

def format_faz6_message(result: dict) -> str:
    if not isinstance(result, dict):
        return f"❌ *FAZ-6 HATA*\nGeçersiz sonuç tipi: {type(result).__name__}"

    status = result.get("status", "ok")
    if status != "ok":
        detail = result.get("detail") or f"Detay yok. Ham sonuç: {repr(result)}"
        return f"❌ *FAZ-6 HATA*\n{detail}"

    mode = result.get("mode", "").upper()
    output = result.get("result", {})
    preds = output.get("predictions") or output.get("portfolio") or []

    text = f"🧠 *FAZ-6 {mode} SONUCU*\n\n"

    for p in preds:
        text += (
            f"📌 {p.get('id')}\n"
            f"🎯 {p.get('pick')} ({p.get('market')})\n"
            f"📈 Güven: {p.get('confidence')} | Edge: {p.get('edge')}\n"
            f"💰 Stake: {p.get('recommended_stake')}\n"
            f"— — —\n"
        )

    return text[:3800]


# ============================================================
#        NEW — FAZ-6 KUPON MOTORU (3 SEVİYE – main.py inside)
# ============================================================

def build_coupon_message(result: dict) -> str:
    """
    3 seviyeli FAZ-6 kupon motoru:
    - Kupon 1: Güvenli
    - Kupon 2: Orta Risk
    - Kupon 3: Edge
    """

    status = result.get("status", "ok")
    if status != "ok":
        return f"❌ Kupon üretilemedi:\n{result.get('detail')}"

    preds = (
        result.get("result", {}).get("portfolio")
        or result.get("result", {}).get("predictions")
        or []
    )

    if not preds:
        return "⚠ Kupon oluşturmak için yeterli maç yok."

    # 1) Güvenli
    safe = sorted(preds, key=lambda p: p.get("confidence", 0), reverse=True)[:3]

    # 2) Orta Risk (conf + edge)
    medium = sorted(
        preds,
        key=lambda p: (p.get("confidence", 0) * 0.6 + p.get("edge", 0) * 0.4),
        reverse=True,
    )[3:6]

    # 3) Edge Kuponu
    high_edge = sorted(preds, key=lambda p: p.get("edge", 0), reverse=True)[6:9]

    coupons = [
        ("🔥 Kupon 1 (Güvenli)", safe),
        ("🚀 Kupon 2 (Orta Risk)", medium),
        ("⚡ Kupon 3 (Edge)", high_edge),
    ]

    text = "💵 *FAZ-6 Kupon Önerileri*\n\n"

    for title, coupon in coupons:
        if not coupon:
            continue

        text += f"{title}\n"
        total_stake = 0.0

        for p in coupon:
            stake = p.get("recommended_stake", 1.0)
            total_stake += stake

            text += (
                f"• {p['id']} → {p['pick']} ({p['market']})\n"
                f"  Güven: {p['confidence']} | Edge: {p['edge']} | Stake: {stake}\n"
            )

        text += f"💰 Toplam Stake: {round(total_stake, 2)}\n"
        text += "— — —\n"

    return text[:3800]


# ============================================================
#                    FAZ-3 TELEGRAM KOMUTLARI
# ============================================================

@bot.message_handler(commands=["start"])
def start_cmd(message):
    bot.reply_to(
        message,
        "🔥 Bot aktif!\nFAZ-3 + FAZ-4 + FAZ-5 + FAZ-6 bağlı.\nKomut listesi için /help yaz."
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
/faz6_coupon - FAZ-6 Kupon (3 kupon)
/cupon - Kısa komut (3 kupon)
"""
    )


@bot.message_handler(commands=["status"])
def status_cmd(message):
    bot.reply_to(message, "🟢 Sistem stabil.\nFAZ-4 aktif.\nFAZ-6 online.")


# ============================================================
#                       FAZ-4 NBA KOMUTU
# ============================================================

@bot.message_handler(commands=["simulate_nba"])
def simulate_nba_cmd(message):
    bot.send_message(message.chat.id, "🏀 Simülasyon başlatılıyor...")

    games: List[NBAGameState] = fetch_nba_live_games()
    if not games:
        bot.send_message(message.chat.id, "Canlı NBA verisi bulunamadı.")
        return

    results = [_simple_sim_from_game(g) for g in games]
    analysis = analyze_live_games(games)

    reply = "📊 *NBA Simülasyon Sonuçları*\n\n"
    for r in results:
        reply += (
            f"🏠 {r['home']} vs ✈️ {r['away']}\n"
            f"📈 Tahmini Skor: {r['score_est']}\n"
            f"⏱ Tempo: {r['pace_est']}\n"
            f"🎯 Kazanan: {r['pick']} ({int(r['confidence'] * 100)}%)\n\n"
        )

    reply += "🧠 Ham Analiz:\n" + analysis
    bot.send_message(message.chat.id, reply, parse_mode="Markdown")


# ============================================================
#                       FAZ-5 ENGINE
# ============================================================

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


# ============================================================
#                       FAZ-6 ENGINE WRAPPER
# ============================================================

from faz6_engine import run_faz6_engine as _raw_run_faz6_engine


def safe_run_faz6_engine(mode: str) -> dict:
    try:
        result = _raw_run_faz6_engine(mode=mode)
        if not isinstance(result, dict):
            return {"status": "error", "detail": "Motor geçersiz veri döndürdü."}
        if "status" not in result:
            result = {"status": "ok", **result}
        return result
    except Exception as e:
        return {"status": "error", "detail": f"FAZ-6 motor exception: {e!r}"}


def _run_faz6_and_reply(message, mode: str):
    result = safe_run_faz6_engine(mode)
    msg = format_faz6_message(result)
    bot.reply_to(message, msg, parse_mode="Markdown")


# FAZ-6 Komutları
@bot.message_handler(commands=["faz6_test"])
def faz6_test_cmd(message): _run_faz6_and_reply(message, "test")

@bot.message_handler(commands=["faz6_auto"])
def faz6_auto_cmd(message): _run_faz6_and_reply(message, "auto")

@bot.message_handler(commands=["faz6_risk"])
def faz6_risk_cmd(message): _run_faz6_and_reply(message, "risk")

@bot.message_handler(commands=["faz6_edge"])
def faz6_edge_cmd(message): _run_faz6_and_reply(message, "edge")

@bot.message_handler(commands=["faz6_real"])
def faz6_real_cmd(message): _run_faz6_and_reply(message, "real")

@bot.message_handler(commands=["faz6_balance"])
def faz6_balance_cmd(message): _run_faz6_and_reply(message, "balance")


# Kupon komutları
@bot.message_handler(commands=["faz6_coupon"])
def faz6_coupon_cmd(message):
    result = safe_run_faz6_engine("balance")
    msg = build_coupon_message(result)
    bot.reply_to(message, msg, parse_mode="Markdown")

@bot.message_handler(commands=["cupon"])
def cupon_cmd(message):
    result = safe_run_faz6_engine("balance")
    msg = build_coupon_message(result)
    bot.reply_to(message, msg, parse_mode="Markdown")


# ============================================================
#                FLY.IO HEALTHCHECK SERVER
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")


def start_health_server():
    server = HTTPServer(("0.0.0.0", 8080), HealthHandler)
    print("INFO: Health server 0.0.0.0:8080 üzerinde çalışıyor.")
    server.serve_forever()


# ============================================================
#                    HEARTBEAT (ANTI-IDLE)
# ============================================================

def heartbeat():
    while True:
        try:
            requests.get("http://127.0.0.1:8080", timeout=3)
        except Exception:
            pass
        time.sleep(20)


# ============================================================
#                    BOT POLLING LOOP
# ============================================================

def start_bot():
    while True:
        try:
            print("INFO: Telegram bot polling başlıyor...")
            bot.infinity_polling(
                skip_pending=True,
                timeout=60,
                long_polling_timeout=60,
            )
        except Exception as e:
            print(f"ERROR: Polling hata verdi: {e!r}")
            time.sleep(3)


# ============================================================
#                      ÇALIŞTIRMA NOKTASI
# ============================================================

def main():
    print("INFO: Bot başlatıldı. Tüm motorlar aktif.")

    Thread(target=start_health_server, daemon=True).start()
    Thread(target=heartbeat, daemon=True).start()
    start_bot()


if __name__ == "__main__":
    main() 
